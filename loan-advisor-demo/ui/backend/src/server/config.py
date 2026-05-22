"""Server configuration settings."""

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    host: str = os.getenv("SERVER_HOST", "0.0.0.0")
    port: int = int(os.getenv("SERVER_PORT", "8888"))
    log_level: str = os.getenv("LOG_LEVEL", "info")
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:4000")
    app_name: str = os.getenv("APP_NAME", "loan_advisor_app")
    user_id: str = os.getenv("USER_ID", "demo_user")
    session_timeout_seconds: int = int(os.getenv("SESSION_TIMEOUT_SECONDS", "3600"))
    use_in_memory_services: bool = os.getenv("USE_IN_MEMORY_SERVICES", "true").lower() == "true"


class EndpointConfig:
    AGENT_PATH = "/agent"
    ROOT_PATH = "/"
    HEALTH_PATH = "/health"
