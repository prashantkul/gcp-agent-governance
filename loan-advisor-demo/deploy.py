import os
import vertexai
from vertexai import agent_engines
from vertexai import types
from dotenv import load_dotenv
import warnings

warnings.filterwarnings("ignore", category=UserWarning, message=r".*\[EXPERIMENTAL\].*")

load_dotenv()

from app.agent import app

GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "privacy-ml-lab1")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "gs://privacy-ml-lab1-agent-staging")
AGENT_RUNTIME_DISPLAY_NAME = os.environ.get("AGENT_RUNTIME_DISPLAY_NAME", "loan-advisor-demo")
MAIL_AUTH_RESOURCE_NAME = os.environ.get("MAIL_AUTH_RESOURCE_NAME", "")
BQ_AUTH_RESOURCE_NAME = os.environ.get("BQ_AUTH_RESOURCE_NAME", "")
CONTINUE_URI = os.environ.get("CONTINUE_URI", "")


def deploy_agent():
    print(f"Initializing Vertex AI for project: {GOOGLE_CLOUD_PROJECT}, location: {LOCATION}")

    client = vertexai.Client(
        project=GOOGLE_CLOUD_PROJECT,
        location=LOCATION,
        http_options=dict(api_version="v1beta1"),
    )

    adk_app = agent_engines.AdkApp(app=app)

    print("Checking for existing deployment...")
    agents_iterator = client.agent_engines.list(
        config={"filter": f'display_name="{AGENT_RUNTIME_DISPLAY_NAME}"'}
    )
    all_matches = list(agents_iterator)
    target_agent = max(all_matches, key=lambda x: x.api_resource.create_time) if all_matches else None

    config_params = {
        "display_name": AGENT_RUNTIME_DISPLAY_NAME,
        "identity_type": types.IdentityType.AGENT_IDENTITY,
        "agent_framework": "google-adk",
        "requirements": [
            "google-cloud-aiplatform[agent_engines,adk]==1.153.1",
            "google-adk[agent-identity]==1.34.0",
            "httpx==0.28.1",
            "python-dotenv>=1.0.1",
            "urllib3>=2.0.0",
            "cloudpickle",
            "pydantic",
        ],
        "staging_bucket": STAGING_BUCKET,
        "python_version": "3.13",
        "env_vars": {
            "GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES": "False",
            "MAIL_AUTH_RESOURCE_NAME": MAIL_AUTH_RESOURCE_NAME,
            "BQ_AUTH_RESOURCE_NAME": BQ_AUTH_RESOURCE_NAME,
            "CONTINUE_URI": CONTINUE_URI,
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        },
        "extra_packages": ["app"],
    }

    try:
        if target_agent:
            name = target_agent.api_resource.name
            print(f"Found existing deployment ({name}). Updating...")
            remote_app = client.agent_engines.update(
                name=name, agent=adk_app, config=config_params
            )
            print("Agent Runtime updated successfully!")
        else:
            print("Creating new Agent Runtime...")
            remote_app = client.agent_engines.create(
                agent=adk_app, config=config_params
            )
            print("Agent Runtime created successfully!")
            print("Set IAM role (roles/iamconnectors.user) on the Agent Identity.")

        print(f"Resource Name: {remote_app.api_resource.name}")
        print(f"Agent Identity: principal://{remote_app.api_resource.spec.effective_identity}")
        return remote_app
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Failed to deploy: {e}")
        return None


if __name__ == "__main__":
    deploy_agent()
