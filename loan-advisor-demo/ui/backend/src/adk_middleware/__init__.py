"""ADK Middleware for AG-UI Protocol.

Bridges Google ADK agents to the AG-UI protocol for use with CopilotKit.
"""

from .adk_agent import ADKAgent
from .agent_registry import AgentRegistry
from .event_translator import EventTranslator
from .session_manager import SessionManager
from .endpoint import add_adk_fastapi_endpoint

__all__ = [
    "ADKAgent",
    "AgentRegistry",
    "EventTranslator",
    "SessionManager",
    "add_adk_fastapi_endpoint",
]

__version__ = "0.1.0"
