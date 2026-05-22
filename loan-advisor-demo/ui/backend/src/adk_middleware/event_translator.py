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
    RunFinishedEvent,
)

import logging

logger = logging.getLogger(__name__)

# Shared store for OAuth consent nonces — written here, read by /commit endpoint
auth_consent_store: dict[str, dict] = {}


class EventTranslator:
    """Translates Google ADK events to AG-UI protocol events."""

    def __init__(self):
        self._active_tool_calls: Dict[str, str] = {}
        self._streaming_message_id: Optional[str] = None
        self._is_streaming: bool = False
        self._auth_interrupt: Optional[Dict[str, Any]] = None

    @property
    def has_auth_interrupt(self) -> bool:
        """True if an auth request was translated and an interrupt should be emitted."""
        return self._auth_interrupt is not None

    def get_auth_interrupt_event(self, thread_id: str, run_id: str) -> RunFinishedEvent:
        """Build a RunFinishedEvent with interrupt outcome for OAuth auth."""
        interrupts = self._auth_interrupt.get("interrupts", []) if self._auth_interrupt else []
        return RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            threadId=thread_id,
            runId=run_id,
            result={
                "outcome": {
                    "type": "interrupt",
                    "interrupts": interrupts,
                },
            },
        )

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

            # Handle auth requests — surface the OAuth URL to the user
            if (
                hasattr(adk_event, "actions")
                and adk_event.actions
                and hasattr(adk_event.actions, "requested_auth_configs")
                and adk_event.actions.requested_auth_configs
            ):
                async for event in self._translate_auth_request(
                    adk_event.actions.requested_auth_configs, thread_id, run_id
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

    async def _translate_auth_request(
        self,
        requested_auth_configs: dict,
        thread_id: str = "",
        run_id: str = "",
    ) -> AsyncGenerator[BaseEvent, None]:
        """Surface OAuth auth URLs as a chat message and emit an AG-UI interrupt."""
        interrupts = []

        for tool_name, auth_config in requested_auth_configs.items():
            # Dump the full auth config to find the right URL
            config_dump = None
            try:
                if hasattr(auth_config, "model_dump"):
                    config_dump = auth_config.model_dump()
                else:
                    config_dump = vars(auth_config)
            except Exception:
                config_dump = {"raw": str(auth_config)}

            logger.info(f"Auth config for {tool_name}: {json.dumps(config_dump, indent=2, default=str)}")

            # Extract the OAuth auth_uri and nonce from exchanged_auth_credential
            auth_url = None
            nonce = None
            exchanged = config_dump.get("exchanged_auth_credential", {})
            if isinstance(exchanged, dict):
                oauth2 = exchanged.get("oauth2", {})
                if isinstance(oauth2, dict):
                    auth_url = oauth2.get("auth_uri")
                    nonce = oauth2.get("nonce")

            # Use tool_name as the function_call_id (matches ADK convention)
            function_call_id = tool_name

            # Store nonce + full auth config for /commit callback and resume
            if nonce:
                auth_consent_store["latest"] = {
                    "consent_nonce": nonce,
                    "user_id": "prashant@pskulkarni.altostrat.com",
                    "tool_name": tool_name,
                    "auth_config": config_dump,
                    "function_call_id": function_call_id,
                    "thread_id": thread_id,
                }
                logger.info(f"Stored consent nonce + thread_id={thread_id}, function_call_id={function_call_id}")

            if not auth_url:
                scheme = config_dump.get("auth_scheme", {})
                if isinstance(scheme, dict):
                    auth_url = scheme.get("authorization_url") or scheme.get("continue_uri")

            # Emit text message with the auth link (user needs to click it)
            msg_id = str(uuid.uuid4())
            yield TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=msg_id,
                role="assistant",
            )

            if auth_url and "accounts.google.com" in auth_url:
                yield TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=msg_id,
                    delta=f"🔐 **Authentication required** to access your data.\n\n[Click here to authorize access]({auth_url})\n\nA new window will open for Google sign-in. After you authorize, the conversation will resume automatically.",
                )
            else:
                yield TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=msg_id,
                    delta=f"🔐 **Authentication required** for `{tool_name}`.\n\nAuth URL: {auth_url or 'Not available'}",
                )

            yield TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=msg_id,
            )

            # Collect interrupt for this auth request
            interrupts.append({
                "id": function_call_id,
                "reason": "input_required",
                "message": f"Authentication required for {tool_name}",
                "data": {
                    "auth_url": auth_url,
                    "tool_name": tool_name,
                },
            })

        logger.info(f"Auth requested for tools: {list(requested_auth_configs.keys())}")

        # Signal that this run is an auth interrupt so _run_adk_in_background
        # can emit RunFinished with the interrupt outcome instead of a normal finish.
        self._auth_interrupt = {
            "thread_id": thread_id,
            "run_id": run_id,
            "interrupts": interrupts,
        }

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
