"""Event translator for converting ADK events to AG-UI protocol events."""

from typing import AsyncGenerator, Optional, Dict, Any
import uuid
import json

from google.genai import types
from google.adk.events import Event as ADKEvent

from ag_ui.core import (
    BaseEvent,
    EventType,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    StateSnapshotEvent,
    StateDeltaEvent,
    CustomEvent,
)

import logging

logger = logging.getLogger(__name__)


class EventTranslator:
    """Translates Google ADK events to AG-UI protocol events."""

    def __init__(self):
        self._active_tool_calls: Dict[str, str] = {}
        self._streaming_message_id: Optional[str] = None
        self._is_streaming: bool = False

    async def translate(
        self,
        adk_event: ADKEvent,
        thread_id: str,
        run_id: str,
    ) -> AsyncGenerator[BaseEvent, None]:
        try:
            is_partial = getattr(adk_event, "partial", False)
            turn_complete = getattr(adk_event, "turn_complete", False)

            is_final_response = False
            if hasattr(adk_event, "is_final_response") and callable(
                adk_event.is_final_response
            ):
                is_final_response = adk_event.is_final_response()
            elif hasattr(adk_event, "is_final_response"):
                is_final_response = adk_event.is_final_response

            logger.debug(
                f"ADK Event: partial={is_partial}, turn_complete={turn_complete}, "
                f"is_final_response={is_final_response}"
            )

            if hasattr(adk_event, "author") and adk_event.author == "user":
                return

            # Handle text content
            if (
                adk_event.content
                and hasattr(adk_event.content, "parts")
                and adk_event.content.parts
            ):
                async for event in self._translate_text_content(
                    adk_event, thread_id, run_id
                ):
                    yield event

            # Handle function calls
            if hasattr(adk_event, "get_function_calls"):
                function_calls = adk_event.get_function_calls()
                if function_calls:
                    async for event in self._translate_function_calls(function_calls):
                        yield event

            # Handle function responses
            if hasattr(adk_event, "get_function_responses"):
                function_responses = adk_event.get_function_responses()
                if function_responses:
                    async for event in self._translate_function_response(
                        function_responses
                    ):
                        yield event

            # Handle state changes
            if (
                hasattr(adk_event, "actions")
                and adk_event.actions
                and hasattr(adk_event.actions, "state_delta")
                and adk_event.actions.state_delta
            ):
                yield self._create_state_delta_event(
                    adk_event.actions.state_delta, thread_id, run_id
                )

            # Handle custom events
            if hasattr(adk_event, "custom_data") and adk_event.custom_data:
                yield CustomEvent(
                    type=EventType.CUSTOM,
                    name="adk_metadata",
                    value=adk_event.custom_data,
                )

        except Exception as e:
            logger.error(f"Error translating ADK event: {e}", exc_info=True)

    async def _translate_text_content(
        self,
        adk_event: ADKEvent,
        thread_id: str,
        run_id: str,
    ) -> AsyncGenerator[BaseEvent, None]:
        text_parts = []
        for part in adk_event.content.parts:
            if part.text:
                text_parts.append(part.text)

        if not text_parts:
            return

        is_partial = getattr(adk_event, "partial", False)

        is_final_response = False
        if hasattr(adk_event, "is_final_response") and callable(
            adk_event.is_final_response
        ):
            is_final_response = adk_event.is_final_response()
        elif hasattr(adk_event, "is_final_response"):
            is_final_response = adk_event.is_final_response

        should_send_end = is_final_response and not is_partial

        # Skip final response events to avoid duplicate content
        if is_final_response:
            if self._is_streaming and self._streaming_message_id:
                yield TextMessageEndEvent(
                    type=EventType.TEXT_MESSAGE_END,
                    message_id=self._streaming_message_id,
                )
                self._streaming_message_id = None
                self._is_streaming = False
            return

        combined_text = "".join(text_parts)

        if not self._is_streaming:
            self._streaming_message_id = str(uuid.uuid4())
            self._is_streaming = True

            yield TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=self._streaming_message_id,
                role="assistant",
            )

        if combined_text:
            yield TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=self._streaming_message_id,
                delta=combined_text,
            )

        if should_send_end:
            yield TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=self._streaming_message_id,
            )
            self._streaming_message_id = None
            self._is_streaming = False

    async def _translate_function_calls(
        self,
        function_calls: list[types.FunctionCall],
    ) -> AsyncGenerator[BaseEvent, None]:
        for func_call in function_calls:
            tool_call_id = getattr(func_call, "id", str(uuid.uuid4()))
            self._active_tool_calls[tool_call_id] = tool_call_id

            yield ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=tool_call_id,
                tool_call_name=func_call.name,
                parent_message_id=None,
            )

            if hasattr(func_call, "args") and func_call.args:
                args_str = (
                    json.dumps(func_call.args)
                    if isinstance(func_call.args, dict)
                    else str(func_call.args)
                )
                yield ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call_id,
                    delta=args_str,
                )

            yield ToolCallEndEvent(
                type=EventType.TOOL_CALL_END,
                tool_call_id=tool_call_id,
            )
            self._active_tool_calls.pop(tool_call_id, None)

    async def _translate_function_response(
        self,
        function_response: list[types.FunctionResponse],
    ) -> AsyncGenerator[BaseEvent, None]:
        for func_response in function_response:
            tool_call_id = getattr(func_response, "id", str(uuid.uuid4()))
            yield ToolCallResultEvent(
                message_id=str(uuid.uuid4()),
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=tool_call_id,
                content=json.dumps(func_response.response),
            )

    def _create_state_delta_event(
        self,
        state_delta: Dict[str, Any],
        thread_id: str,
        run_id: str,
    ) -> StateDeltaEvent:
        patches = []
        for key, value in state_delta.items():
            patches.append({"op": "add", "path": f"/{key}", "value": value})
        return StateDeltaEvent(type=EventType.STATE_DELTA, delta=patches)

    def _create_state_snapshot_event(
        self,
        state_snapshot: Dict[str, Any],
    ) -> StateSnapshotEvent:
        return StateSnapshotEvent(
            type=EventType.STATE_SNAPSHOT,
            snapshot=state_snapshot,
        )

    async def force_close_streaming_message(self) -> AsyncGenerator[BaseEvent, None]:
        if self._is_streaming and self._streaming_message_id:
            logger.warning(
                f"Force-closing unterminated streaming message: {self._streaming_message_id}"
            )
            yield TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=self._streaming_message_id,
            )
            self._streaming_message_id = None
            self._is_streaming = False

    def reset(self):
        self._active_tool_calls.clear()
        self._streaming_message_id = None
        self._is_streaming = False
