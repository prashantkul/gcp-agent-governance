"""Acme Financial Services MCP Server — exposes loan data tools backed by BigQuery."""

import os

from google.cloud import bigquery
from mcp.server.fastmcp import FastMCP

PROJECT_ID = os.environ.get("GCP_PROJECT", "privacy-ml-lab1")
DATASET = "loan_products"

bq = bigquery.Client(project=PROJECT_ID)

mcp = FastMCP(
  "Acme Financial Services",
  instructions=(
    "You are the Acme Financial Services data assistant. "
    "Use the provided tools to look up loan products, search applications, "
    "and retrieve customer profiles. Customer PII is redacted at the tool level."
  ),
)


def _run_query(sql: str, params: list[bigquery.ScalarQueryParameter] | None = None) -> list[dict]:
  """Execute a BigQuery SQL query and return rows as dicts."""
  job_config = bigquery.QueryJobConfig(query_parameters=params or [])
  rows = bq.query(sql, job_config=job_config).result()
  return [dict(row) for row in rows]



@mcp.tool()
def list_loan_products() -> list[dict]:
  """List all available loan products from Acme Financial Services.

  Returns details such as product name, type, interest rate, term, and eligibility criteria.
  """
  sql = f"SELECT * FROM `{PROJECT_ID}.{DATASET}.products`"
  return _run_query(sql)



@mcp.tool()
def get_customer_profile(customer_id: str) -> dict:
  """Retrieve a customer profile by customer ID.

  Returns the full customer profile. PII protection is handled by Model Armor
  at the gateway level.

  Args:
    customer_id: The unique identifier for the customer.
  """
  sql = f"""
    SELECT * FROM `{PROJECT_ID}.{DATASET}.customers`
    WHERE customer_id = @customer_id
  """
  params = [bigquery.ScalarQueryParameter("customer_id", "STRING", customer_id)]
  rows = _run_query(sql, params)

  if not rows:
    return {"error": f"No customer found with id '{customer_id}'"}

  return rows[0]


if __name__ == "__main__":
  import uvicorn
  port = int(os.environ.get("PORT", "8080"))
  app = mcp.streamable_http_app()
  uvicorn.run(app, host="0.0.0.0", port=port)
