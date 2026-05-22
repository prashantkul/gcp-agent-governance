import logging

from dotenv import load_dotenv
from vertexai.agent_engines.templates.adk import AdkApp

from app.agent import app as adk_app

load_dotenv()
logging.basicConfig(level=logging.INFO)

agent_runtime = AdkApp(app=adk_app)
