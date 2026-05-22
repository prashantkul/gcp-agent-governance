#!/usr/bin/env python
"""Main entry point for the Loan Advisor AG-UI backend server."""

import uvicorn
import logging
import asyncio
from server import create_app, ServerConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    server_config = ServerConfig()

    logger.info("Starting Loan Advisor AG-UI backend server...")
    logger.info(f"  Host: {server_config.host}")
    logger.info(f"  Port: {server_config.port}")
    logger.info(f"  CORS origins: {server_config.cors_origins}")

    app = create_app(server_config)

    uvicorn_config = uvicorn.Config(
        app,
        host=server_config.host,
        port=server_config.port,
        log_level=server_config.log_level,
    )

    server = uvicorn.Server(uvicorn_config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
