"""Singleton registry for mapping AG-UI agent IDs to ADK agents."""

from typing import Dict, Optional
from google.adk.agents import BaseAgent
import logging

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Singleton registry mapping AG-UI agent IDs to ADK agent instances."""

    _instance = None

    def __init__(self):
        self._registry: Dict[str, BaseAgent] = {}
        self._default_agent: Optional[BaseAgent] = None

    @classmethod
    def get_instance(cls) -> "AgentRegistry":
        if cls._instance is None:
            cls._instance = cls()
            logger.info("Initialized AgentRegistry singleton")
        return cls._instance

    @classmethod
    def reset_instance(cls):
        cls._instance = None

    def register_agent(self, agent_id: str, agent: BaseAgent):
        self._registry[agent_id] = agent
        logger.info(f"Registered agent '{agent.name}' with ID '{agent_id}'")

    def set_default_agent(self, agent: BaseAgent):
        self._default_agent = agent
        logger.info(f"Set default agent to '{agent.name}'")

    def get_agent(self, agent_id: str) -> BaseAgent:
        if agent_id in self._registry:
            return self._registry[agent_id]
        if self._default_agent:
            return self._default_agent
        registered_ids = list(self._registry.keys())
        raise ValueError(
            f"No agent found for ID '{agent_id}'. "
            f"Registered IDs: {registered_ids}."
        )

    def has_agent(self, agent_id: str) -> bool:
        try:
            self.get_agent(agent_id)
            return True
        except ValueError:
            return False

    def list_registered_agents(self) -> Dict[str, str]:
        return {
            agent_id: agent.name
            for agent_id, agent in self._registry.items()
        }
