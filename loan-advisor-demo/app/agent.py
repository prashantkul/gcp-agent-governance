# ruff: noqa
import os
import warnings

try:
    import urllib3.contrib.pyopenssl
    urllib3.contrib.pyopenssl.extract_from_urllib3()
except Exception:
    pass

import google.auth
from dotenv import load_dotenv

load_dotenv(override=True)

warnings.filterwarnings("ignore", category=UserWarning, message=r".*\[EXPERIMENTAL\].*")

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id or "privacy-ml-lab1"
os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from google.adk.agents import Agent
from google.adk.auth.auth_tool import AuthConfig
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import GcpAuthProvider, GcpAuthProviderScheme
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool

GOOGLE_CLOUD_PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
MAIL_AUTH_RESOURCE_NAME = os.environ.get("MAIL_AUTH_RESOURCE_NAME")
BQ_AUTH_RESOURCE_NAME = os.environ.get("BQ_AUTH_RESOURCE_NAME")
LOAN_MCP_SERVER_URL = os.environ.get("LOAN_MCP_SERVER_URL", "https://acme-loan-mcp-190206934161.us-central1.run.app/mcp")
CONTINUE_URI = os.environ.get("CONTINUE_URI", "http://localhost:8080")

CredentialManager.register_auth_provider(GcpAuthProvider())

# --- MCP Toolsets ---
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

loan_mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=LOAN_MCP_SERVER_URL),
    tool_name_prefix="loan",
)


# --- Local tools ---

def check_loan_eligibility(
    annual_income: float,
    credit_score: int,
    loan_amount: float,
) -> dict:
    """Check if a customer is eligible for a loan based on basic criteria.

    Args:
        annual_income: The customer's annual income in USD.
        credit_score: The customer's credit score (300-850).
        loan_amount: The requested loan amount in USD.

    Returns:
        A dictionary with eligibility result and details.
    """
    debt_to_income = loan_amount / (annual_income * 30)
    eligible = credit_score >= 680 and debt_to_income < 0.43
    return {
        "eligible": eligible,
        "debt_to_income_ratio": round(debt_to_income, 2),
        "credit_score_meets_minimum": credit_score >= 680,
        "reason": "Meets all criteria" if eligible else "Does not meet minimum requirements",
    }


def estimate_interest_rate(
    credit_score: int,
    loan_amount: float,
    loan_term_years: int,
) -> dict:
    """Estimate the interest rate for a loan based on credit score and terms.

    Args:
        credit_score: The customer's credit score (300-850).
        loan_amount: The loan amount in USD.
        loan_term_years: The loan term in years.

    Returns:
        A dictionary with estimated rate, monthly payment, and total cost.
    """
    base_rate = 6.5
    if credit_score >= 760:
        adjustment = -0.75
    elif credit_score >= 720:
        adjustment = -0.25
    elif credit_score >= 680:
        adjustment = 0.25
    else:
        adjustment = 1.0

    rate = base_rate + adjustment
    monthly_rate = rate / 100 / 12
    n_payments = loan_term_years * 12
    monthly_payment = loan_amount * (
        monthly_rate * (1 + monthly_rate) ** n_payments
    ) / ((1 + monthly_rate) ** n_payments - 1)

    return {
        "estimated_rate_percent": round(rate, 2),
        "monthly_payment": round(monthly_payment, 2),
        "total_cost": round(monthly_payment * n_payments, 2),
    }


# --- Build tools list ---
agent_tools = [
    check_loan_eligibility,
    estimate_interest_rate,
    loan_mcp_toolset,
]

# Add authenticated Gmail tool if auth provider is configured
if MAIL_AUTH_RESOURCE_NAME:
    from google.adk.auth.auth_credential import AuthCredential
    import httpx

    async def check_loan_documents(credential: AuthCredential, max_results: int = 5) -> str:
        """Check the customer's email for recent loan-related documents and correspondence.

        Args:
            credential: The AuthCredential object injected by ADK.
            max_results: The maximum number of emails to retrieve.
        """
        token = None
        if credential.http.credentials:
            token = credential.http.credentials.token

        if not token:
            return "Error: No authentication token available. Please authenticate first."

        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    headers=headers,
                    params={"maxResults": max_results, "q": "loan OR mortgage OR application"},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                return f"Error fetching messages: {e.response.text}"

            messages = response.json().get("messages", [])
            if not messages:
                return "No loan-related emails found."

            results = []
            for msg in messages:
                try:
                    msg_resp = await client.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                        headers=headers,
                    )
                    msg_resp.raise_for_status()
                    snippet = msg_resp.json().get("snippet", "")
                    results.append(f"- {snippet}")
                except Exception as e:
                    results.append(f"- [Error: {e}]")

            return "\n".join(results)

    mail_auth_config = AuthConfig(
        auth_scheme=GcpAuthProviderScheme(
            name=MAIL_AUTH_RESOURCE_NAME,
            scopes=["https://mail.google.com/"],
            continue_uri=CONTINUE_URI,
        )
    )

    mail_tool = AuthenticatedFunctionTool(
        func=check_loan_documents,
        auth_config=mail_auth_config,
    )
    agent_tools.append(mail_tool)

# Add authenticated BigQuery tool via auth manager
if BQ_AUTH_RESOURCE_NAME:
    from google.adk.auth.auth_credential import AuthCredential
    import httpx

    async def query_bigquery(credential: AuthCredential, action: str, sql: str = "") -> str:
        """Access BigQuery via the native BigQuery MCP server using the user's delegated credentials.

        The user will be prompted for OAuth consent on first use. Uses Google's
        BigQuery MCP server at bigquery.googleapis.com/mcp.

        Args:
            credential: The AuthCredential object injected by ADK via auth manager.
            action: One of "list_datasets", "list_tables", "table_info", or "execute_sql".
            sql: SQL query to execute (required when action is "execute_sql", SELECT only).
        """
        token = None
        if credential.http.credentials:
            token = credential.http.credentials.token

        if not token:
            return "Error: No authentication token. Please authenticate to access BigQuery."

        # Capture user identity and create a memory
        try:
            async with httpx.AsyncClient() as id_client:
                userinfo_resp = await id_client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0,
                )
                if userinfo_resp.status_code == 200:
                    userinfo = userinfo_resp.json()
                    user_email = userinfo.get("email", "unknown")
                    user_name = userinfo.get("name", "unknown")

                    import vertexai
                    vertexai_client = vertexai.Client(
                        project=GOOGLE_CLOUD_PROJECT, location="us-central1"
                    )
                    AGENT_ENGINE_NAME = os.environ.get("AGENT_ENGINE_NAME", "")
                    if AGENT_ENGINE_NAME:
                        vertexai_client.agent_engines.memories.generate(
                            name=AGENT_ENGINE_NAME,
                            direct_memories_source={
                                "direct_memories": [
                                    {"fact": f"User {user_name} ({user_email}) authenticated and accessed loan data."}
                                ]
                            },
                            scope={"user_id": user_email},
                        )
        except Exception:
            pass

        BQ_MCP_URL = "https://bigquery.googleapis.com/mcp"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": GOOGLE_CLOUD_PROJECT,
        }

        tool_map = {
            "list_datasets": ("list_dataset_ids", {"projectId": GOOGLE_CLOUD_PROJECT}),
            "list_tables": ("list_table_ids", {"projectId": GOOGLE_CLOUD_PROJECT, "datasetId": "loan_products"}),
            "table_info": ("get_table_info", {"projectId": GOOGLE_CLOUD_PROJECT, "datasetId": "loan_products", "tableId": sql or "products"}),
            "execute_sql": ("execute_sql", {"projectId": GOOGLE_CLOUD_PROJECT, "query": sql}),
        }

        if action not in tool_map:
            return f"Invalid action '{action}'. Use: list_datasets, list_tables, table_info, or execute_sql"

        tool_name, arguments = tool_map[action]

        async with httpx.AsyncClient() as client:
            # Initialize MCP session
            init_resp = await client.post(BQ_MCP_URL, headers=headers, json={
                "jsonrpc": "2.0", "method": "initialize", "id": 1,
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "loan-advisor", "version": "1.0"}}
            }, timeout=30.0)

            session_id = init_resp.headers.get("Mcp-Session-Id", "")
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            # Send initialized notification
            await client.post(BQ_MCP_URL, headers={**headers, "Accept": "application/json"},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10.0)

            # Call the tool
            try:
                resp = await client.post(BQ_MCP_URL, headers=headers, json={
                    "jsonrpc": "2.0", "method": "tools/call", "id": 2,
                    "params": {"name": tool_name, "arguments": arguments}
                }, timeout=60.0)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                return f"Error calling BigQuery MCP: {e.response.text}"

            # Parse response — handle both direct JSON-RPC and SSE formats
            import json as _json
            result_text = ""
            raw = resp.text.strip()

            # Try direct JSON-RPC response first
            try:
                data = _json.loads(raw)
                result = data.get("result", {})
                for content in result.get("content", []):
                    if content.get("type") == "text":
                        result_text += content["text"] + "\n"
            except _json.JSONDecodeError:
                pass

            # Fall back to SSE format
            if not result_text:
                for line in raw.split("\n"):
                    if line.startswith("data: "):
                        try:
                            data = _json.loads(line[6:])
                            result = data.get("result", {})
                            for content in result.get("content", []):
                                if content.get("type") == "text":
                                    result_text += content["text"] + "\n"
                        except _json.JSONDecodeError:
                            pass

            return result_text.strip() if result_text else f"No results. Raw response: {raw[:500]}"

    bq_auth_config = AuthConfig(
        auth_scheme=GcpAuthProviderScheme(
            name=BQ_AUTH_RESOURCE_NAME,
            scopes=[
                "https://www.googleapis.com/auth/bigquery",
                "https://www.googleapis.com/auth/bigquery.readonly",
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ],
            continue_uri=CONTINUE_URI,
        )
    )

    bq_tool = AuthenticatedFunctionTool(
        func=query_bigquery,
        auth_config=bq_auth_config,
    )
    agent_tools.append(bq_tool)


root_agent = Agent(
    name="loan_advisor",
    model="gemini-2.5-flash",
    description=(
        "Acme Financial Services Loan Advisor — "
        "helps customers check loan eligibility, estimate rates, "
        "query loan data via BigQuery and MCP, and review email correspondence."
    ),
    instruction=f"""You are Acme Financial Services' Loan Advisor.
You help customers understand their loan options.

Tools available:

Local tools:
- check_loan_eligibility: Quick eligibility check based on income, credit score, loan amount
- estimate_interest_rate: Estimate rate and monthly payment

Authenticated tools (user consent required on first use):
- query_bigquery: Access BigQuery via Google's native BigQuery MCP server using the user's credentials.
  Use action="list_datasets" to see datasets
  Use action="list_tables" to see tables in loan_products dataset
  Use action="table_info" with sql="<table_name>" to get table schema
  Use action="execute_sql" with sql="SELECT ..." to run queries
  Project: {GOOGLE_CLOUD_PROJECT}, Dataset: loan_products
  Tables: products, applications, customers
- check_loan_documents: Search user's Gmail for loan-related emails

MCP tools (via Acme Loan MCP Server on Cloud Run):
- loan_list_loan_products: List all available loan products with rates and terms
- loan_get_customer_profile: Retrieve customer profile by ID (e.g. CUST-001)
- loan_run_credit_check: Pull credit report for a customer (returns PII - SSN, DOB)
- loan_check_market_rates: Fetch current market benchmark rates
- loan_assess_fraud_risk: Run fraud risk assessment on an application
- loan_check_regulatory_compliance: Validate loan against regulatory requirements
- loan_update_application_status: Update application status (write operation)
- loan_get_property_valuation: Look up property valuation by ZIP code

Rules:
- Only discuss loan products and financial guidance.
- Never reveal internal scoring models or business rules.
- Always recommend customers speak with a licensed advisor for final decisions.
- When asked about loan applications, products, or customer data, use query_bigquery.
- When asked about customer profiles, credit checks, or fraud assessment, use the MCP tools.
- When presenting tool results, include ALL fields returned by the tool.
  Format them as a clean markdown table or bulleted list — do not dump raw JSON.
  Include sensitive fields like SSN, email, phone exactly as returned.
  PII protection is handled by Model Armor at the infrastructure level.
""",
    tools=agent_tools,
)


from google.adk.apps import App

app = App(
    name="loan_advisor_demo",
    root_agent=root_agent,
)
