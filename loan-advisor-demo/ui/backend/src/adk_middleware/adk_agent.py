"""Main ADKAgent implementation for bridging AG-UI Protocol with Google ADK."""

from typing import Optional, Dict, Callable, Any, AsyncGenerator, List
import json
import asyncio

from ag_ui.core import (
    RunAgentInput,
    BaseEvent,
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    SystemMessage,
)

from google.adk import Runner
from google.adk.agents import BaseAgent as ADKBaseAgent, RunConfig as ADKRunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory import InMemoryMemoryService
from google.genai import types

from .agent_registry import AgentRegistry
from .event_translator import EventTranslator
from .session_manager import SessionManager
from .execution_state import ExecutionState

import logging

logger = logging.getLogger(__name__)


class ADKAgent:
    """Middleware bridging the AG-UI protocol with Google ADK agents."""

    def __init__(
        self,
        app_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_timeout_seconds: int = 1200,
        use_in_memory_services: bool = True,
        execution_timeout_seconds: int = 600,
        max_concurrent_executions: int = 10,
    ):
        self._static_app_name = app_name
        self._static_user_id = user_id

        self._artifact_service = InMemoryArtifactService() if use_in_memory_services else None
        self._memory_service = InMemoryMemoryService() if use_in_memory_services else None

        session_service = InMemorySessionService()
        self._session_manager = SessionManager.get_instance(
            session_service=session_service,
            memory_service=self._memory_service,
            session_timeout_seconds=session_timeout_seconds,
            auto_cleanup=True,
        )

        self._active_executions: Dict[str, ExecutionState] = {}
        self._execution_timeout = execution_timeout_seconds
        self._max_concurrent = max_concurrent_executions
        self._execution_lock = asyncio.Lock()

    def _get_app_name(self, input_data: RunAgentInput) -> str:
        if self._static_app_name:
            return self._static_app_name
        try:
            registry = AgentRegistry.get_instance()
            adk_agent = registry.get_agent("default")
            return adk_agent.name
        except Exception:
            return "loan_advisor_app"

    def _get_user_id(self, input_data: RunAgentInput) -> str:
        if self._static_user_id:
            return self._static_user_id
        return f"thread_user_{input_data.thread_id}"

    def _default_run_config(self) -> ADKRunConfig:
        return ADKRunConfig(
            streaming_mode=StreamingMode.SSE,
            save_input_blobs_as_artifacts=True,
        )

    def _create_runner(
        self, adk_agent: ADKBaseAgent, app_name: str
    ) -> Runner:
        return Runner(
            app_name=app_name,
            agent=adk_agent,
            session_service=self._session_manager._session_service,
            artifact_service=self._artifact_service,
            memory_service=self._memory_service,
        )

    async def run(
        self, input_data: RunAgentInput, agent_id: str = "default"
    ) -> AsyncGenerator[BaseEvent, None]:
        if self._is_tool_result_submission(input_data):
            async for event in self._handle_tool_result_submission(
                input_data, agent_id
            ):
                yield event
        else:
            async for event in self._start_new_execution(input_data, agent_id):
                yield event

    def _is_tool_result_submission(self, input_data: RunAgentInput) -> bool:
        if not input_data.messages:
            return False
        last_message = input_data.messages[-1]
        return hasattr(last_message, "role") and last_message.role == "tool"

    async def _handle_tool_result_submission(
        self, input_data: RunAgentInput, agent_id: str = "default"
    ) -> AsyncGenerator[BaseEvent, None]:
        tool_results = self._extract_tool_results(input_data)
        if not tool_results:
            yield RunErrorEvent(
                type=EventType.RUN_ERROR,
                message="No tool results found in submission",
                code="NO_TOOL_RESULTS",
            )
            return
        async for event in self._start_new_execution(input_data, agent_id):
            yield event

    def _extract_tool_results(self, input_data: RunAgentInput) -> List[Dict]:
        tool_call_map = {}
        for message in input_data.messages:
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_call_map[tool_call.id] = tool_call.function.name

        most_recent = None
        for message in reversed(input_data.messages):
            if hasattr(message, "role") and message.role == "tool":
                most_recent = message
                break

        if most_recent:
            tool_name = tool_call_map.get(most_recent.tool_call_id, "unknown")
            return [{"tool_name": tool_name, "message": most_recent}]
        return []

    async def _convert_latest_message(
        self, input_data: RunAgentInput
    ) -> Optional[types.Content]:
        if not input_data.messages:
            return None
        for message in reversed(input_data.messages):
            if message.role == "user" and message.content:
                return types.Content(
                    role="user",
                    parts=[types.Part(text=message.content)],
                )
        return None

    async def _ensure_session_exists(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        initial_state: dict,
    ):
        await self._session_manager.get_or_create_session(
            session_id=session_id,
            app_name=app_name,
            user_id=user_id,
            initial_state=initial_state,
        )

    async def _stream_events(
        self, execution: ExecutionState
    ) -> AsyncGenerator[BaseEvent, None]:
        while True:
            try:
                event = await asyncio.wait_for(
                    execution.event_queue.get(), timeout=1.0
                )
                if event is None:
                    execution.is_complete = True
                    break
                yield event
            except asyncio.TimeoutError:
                if execution.is_stale(self._execution_timeout):
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        message="Execution timed out",
                        code="EXECUTION_TIMEOUT",
                    )
                    break
                if execution.task.done():
                    execution.is_complete = True
                    if execution.event_queue.qsize() > 0:
                        continue
                    break

    async def _start_new_execution(
        self, input_data: RunAgentInput, agent_id: str = "default"
    ) -> AsyncGenerator[BaseEvent, None]:
        try:
            yield RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
            )

            async with self._execution_lock:
                if len(self._active_executions) >= self._max_concurrent:
                    await self._cleanup_stale_executions()
                    if len(self._active_executions) >= self._max_concurrent:
                        raise RuntimeError(
                            f"Maximum concurrent executions ({self._max_concurrent}) reached"
                        )

            execution = await self._start_background_execution(
                input_data, agent_id
            )

            async with self._execution_lock:
                self._active_executions[input_data.thread_id] = execution

            async for event in self._stream_events(execution):
                yield event

            yield RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
            )

        except Exception as e:
            logger.error(f"Error in new execution: {e}", exc_info=True)
            yield RunErrorEvent(
                type=EventType.RUN_ERROR,
                message=str(e),
                code="EXECUTION_ERROR",
            )
        finally:
            async with self._execution_lock:
                if input_data.thread_id in self._active_executions:
                    self._active_executions[input_data.thread_id].is_complete = True
                    del self._active_executions[input_data.thread_id]

    async def _start_background_execution(
        self, input_data: RunAgentInput, agent_id: str = "default"
    ) -> ExecutionState:
        event_queue = asyncio.Queue()
        user_id = self._get_user_id(input_data)
        app_name = self._get_app_name(input_data)

        registry = AgentRegistry.get_instance()
        adk_agent = registry.get_agent(agent_id)

        # Handle SystemMessage -- append to agent instructions
        agent_updates = {}
        if input_data.messages and isinstance(input_data.messages[0], SystemMessage):
            system_content = input_data.messages[0].content
            if system_content:
                current_instruction = getattr(adk_agent, "instruction", "") or ""
                new_instruction = (
                    f"{current_instruction}\n\n{system_content}"
                    if current_instruction
                    else system_content
                )
                agent_updates["instruction"] = new_instruction

        if agent_updates:
            adk_agent = adk_agent.model_copy(update=agent_updates)

        task = asyncio.create_task(
            self._run_adk_in_background(
                input_data=input_data,
                adk_agent=adk_agent,
                user_id=user_id,
                app_name=app_name,
                event_queue=event_queue,
            )
        )

        return ExecutionState(
            task=task,
            thread_id=input_data.thread_id,
            event_queue=event_queue,
        )

    async def _run_adk_in_background(
        self,
        input_data: RunAgentInput,
        adk_agent: ADKBaseAgent,
        user_id: str,
        app_name: str,
        event_queue: asyncio.Queue,
    ):
        try:
            runner = self._create_runner(adk_agent=adk_agent, app_name=app_name)
            run_config = self._default_run_config()

            await self._ensure_session_exists(
                app_name, user_id, input_data.thread_id, input_data.state
            )

            if input_data.state:
                await self._session_manager.update_session_state(
                    input_data.thread_id, app_name, user_id, input_data.state
                )

            new_message = await self._convert_latest_message(input_data)

            # Handle tool result submissions
            if self._is_tool_result_submission(input_data):
                tool_results = self._extract_tool_results(input_data)
                parts = []
                for tool_msg in tool_results:
                    tool_call_id = tool_msg["message"].tool_call_id
                    content = tool_msg["message"].content
                    try:
                        result = (
                            json.loads(content)
                            if content and content.strip()
                            else {"success": True, "result": None}
                        )
                    except json.JSONDecodeError:
                        result = {"error": "Invalid JSON in tool result", "raw_content": content}
                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=tool_call_id,
                                name=tool_msg["tool_name"],
                                response=result,
                            )
                        )
                    )
                new_message = types.Content(parts=parts, role="user")

            event_translator = EventTranslator()

            async for adk_event in runner.run_async(
                user_id=user_id,
                session_id=input_data.thread_id,
                new_message=new_message,
                run_config=run_config,
            ):
                if not adk_event.is_final_response():
                    async for ag_ui_event in event_translator.translate(
                        adk_event, input_data.thread_id, input_data.run_id
                    ):
                        await event_queue.put(ag_ui_event)

            # Force close any streaming messages
            async for ag_ui_event in event_translator.force_close_streaming_message():
                await event_queue.put(ag_ui_event)

            # Emit final state snapshot
            final_state = await self._session_manager.get_session_state(
                input_data.thread_id, app_name, user_id
            )
            if final_state:
                ag_ui_event = event_translator._create_state_snapshot_event(
                    final_state
                )
                await event_queue.put(ag_ui_event)

            await event_queue.put(None)

        except Exception as e:
            logger.error(f"Background execution error: {e}", exc_info=True)
            await event_queue.put(
                RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message=str(e),
                    code="BACKGROUND_EXECUTION_ERROR",
                )
            )
            await event_queue.put(None)

    async def _cleanup_stale_executions(self):
        stale_threads = [
            tid
            for tid, execution in self._active_executions.items()
            if execution.is_stale(self._execution_timeout)
        ]
        for thread_id in stale_threads:
            execution = self._active_executions.pop(thread_id)
            await execution.cancel()
            logger.info(f"Cleaned up stale execution for thread {thread_id}")

    async def close(self):
        async with self._execution_lock:
            for execution in self._active_executions.values():
                await execution.cancel()
            self._active_executions.clear()
        await self._session_manager.stop_cleanup_task()
