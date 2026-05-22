import logging
import os
import sys

# Must run before ANY other imports — Agent Engine injects pyopenssl which
# breaks SSL contexts used by the IAM connector credentials client.
try:
    import urllib3.contrib.pyopenssl
    urllib3.contrib.pyopenssl.extract_from_urllib3()
except Exception:
    pass

from dotenv import load_dotenv
from vertexai.agent_engines.templates.adk import AdkApp

from app.agent import app as adk_app

load_dotenv()
logging.basicConfig(level=logging.INFO)

agent_runtime = AdkApp(app=adk_app)
