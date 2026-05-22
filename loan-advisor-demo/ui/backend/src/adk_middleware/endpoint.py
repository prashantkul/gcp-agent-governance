"""FastAPI endpoint for ADK middleware."""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from ag_ui.core import RunAgentInput, RunErrorEvent, EventType
from ag_ui.encoder import EventEncoder
from .adk_agent import ADKAgent

import logging

logger = logging.getLogger(__name__)


def add_adk_fastapi_endpoint(
    app: FastAPI, agent: ADKAgent, path: str = "/"
):
    """Add an ADK middleware endpoint to a FastAPI app.

    Args:
        app: FastAPI application instance
        agent: Configured ADKAgent instance
        path: API endpoint path
    """

    @app.post(path)
    async def adk_endpoint(input_data: RunAgentInput, request: Request):
        accept_header = request.headers.get("accept")
        agent_id = path.lstrip("/")

        encoder = EventEncoder(accept=accept_header)

        async def event_generator():
            try:
                async for event in agent.run(input_data, agent_id):
                    try:
                        encoded = encoder.encode(event)
                        yield encoded
                    except Exception as encoding_error:
                        logger.error(
                            f"Event encoding error: {encoding_error}",
                            exc_info=True,
                        )
                        error_event = RunErrorEvent(
                            type=EventType.RUN_ERROR,
                            message=f"Event encoding failed: {encoding_error!s}",
                            code="ENCODING_ERROR",
                        )
                        try:
                            yield encoder.encode(error_event)
                        except Exception:
                            yield 'event: error\ndata: {"error": "Event encoding failed"}\n\n'
                        break
            except Exception as agent_error:
                logger.error(
                    f"ADKAgent error: {agent_error}", exc_info=True
                )
                try:
                    error_event = RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        message=f"Agent execution failed: {agent_error!s}",
                        code="AGENT_ERROR",
                    )
                    yield encoder.encode(error_event)
                except Exception:
                    yield 'event: error\ndata: {"error": "Agent execution failed"}\n\n'

        return StreamingResponse(
            event_generator(), media_type=encoder.get_content_type()
        )
