"""FastAPI application factory."""

import sys
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from adk_middleware import ADKAgent, AgentRegistry, add_adk_fastapi_endpoint
from .config import ServerConfig, EndpointConfig

logger = logging.getLogger(__name__)


def setup_agent_registry() -> None:
    """Import and register the loan_advisor root_agent from the main app."""
    # Add the project root to sys.path so we can import app.agent
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from app.agent import root_agent

    registry = AgentRegistry.get_instance()
    registry.set_default_agent(root_agent)
    registry.register_agent("agent", root_agent)
    registry.register_agent("loan_advisor", root_agent)

    logger.info(f"Registered loan_advisor agent: {root_agent.name}")


def create_adk_agent(config: ServerConfig) -> ADKAgent:
    return ADKAgent(
        app_name=config.app_name,
        user_id=config.user_id,
        session_timeout_seconds=config.session_timeout_seconds,
        use_in_memory_services=config.use_in_memory_services,
    )


def create_app(config: ServerConfig = None) -> FastAPI:
    if config is None:
        config = ServerConfig()

    setup_agent_registry()

    adk_agent = create_adk_agent(config)

    app = FastAPI(
        title="Loan Advisor AG-UI Backend",
        description="AG-UI protocol backend for the Loan Advisor ADK agent",
        version="1.0.0",
    )

    cors_origins = (
        config.cors_origins.split(",")
        if config.cors_origins != "*"
        else ["*"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register the AG-UI endpoint
    add_adk_fastapi_endpoint(app, adk_agent, path=EndpointConfig.AGENT_PATH)

    @app.get(EndpointConfig.ROOT_PATH)
    async def root():
        return {
            "message": "Loan Advisor AG-UI Backend is running",
            "agent": "loan_advisor",
            "endpoint": EndpointConfig.AGENT_PATH,
        }

    @app.get(EndpointConfig.HEALTH_PATH)
    async def health_check():
        return {"status": "healthy", "service": "loan_advisor_backend"}

    logger.info("FastAPI application created for Loan Advisor")

    return app
