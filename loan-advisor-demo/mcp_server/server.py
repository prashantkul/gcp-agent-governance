"""Acme Financial Services MCP Server — exposes loan data tools backed by BigQuery.

Tools are organized by governance dimension:
  - list_loan_products, get_customer_profile: Core data access
  - check_market_rates: External API access governance
  - run_credit_check: Model Armor PII redaction
  - assess_fraud_risk: Sensitive data handling + audit logging
  - check_regulatory_compliance: Policy enforcement guardrails
  - update_application_status: Write access control (vs read-only)
  - get_property_valuation: Cross-service authorization
"""

import os
from datetime import datetime, timezone

from google.cloud import bigquery
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

PROJECT_ID = os.environ.get("GCP_PROJECT", "privacy-ml-lab1")
DATASET = "loan_products"

bq = bigquery.Client(project=PROJECT_ID)

mcp = FastMCP(
  "Acme Financial Services",
  instructions=(
    "You are the Acme Financial Services data assistant. "
    "Use the provided tools to look up loan products, search applications, "
    "retrieve customer profiles, check market rates, run credit checks, "
    "assess fraud risk, validate regulatory compliance, update application "
    "status, and look up property valuations. "
    "Customer PII is redacted at the gateway level by Model Armor."
  ),
  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _run_query(sql: str, params: list[bigquery.ScalarQueryParameter] | None = None) -> list[dict]:
  """Execute a BigQuery SQL query and return rows as dicts."""
  job_config = bigquery.QueryJobConfig(query_parameters=params or [])
  rows = bq.query(sql, job_config=job_config).result()
  return [dict(row) for row in rows]


def _run_dml(sql: str, params: list[bigquery.ScalarQueryParameter] | None = None) -> int:
  """Execute a BigQuery DML statement and return the number of affected rows."""
  job_config = bigquery.QueryJobConfig(query_parameters=params or [])
  job = bq.query(sql, job_config=job_config)
  job.result()
  return job.num_dml_affected_rows or 0


# ── Core data access tools ──────────────────────────────────────────────────


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
    customer_id: The unique identifier for the customer (e.g. 'CUST-001').
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


# ── 1. External API access governance ───────────────────────────────────────


@mcp.tool()
def check_market_rates(loan_type: str = "all") -> dict:
  """Fetch current market benchmark rates from external sources.

  Pulls rates from Freddie Mac PMMS, Federal Reserve H.15, and Bankrate
  surveys, then compares them against Acme's internal product rates.

  This tool accesses external rate APIs and is subject to Agent Gateway
  rate-limiting and access policies. Agent Identity verification ensures
  only authorized agents can query third-party financial data feeds.

  Args:
    loan_type: Filter by category — 'MORTGAGE', 'AUTO', 'PERSONAL', 'HELOC',
               'REFERENCE', or 'all' for everything.
  """
  if loan_type.lower() == "all":
    sql = f"SELECT * FROM `{PROJECT_ID}.{DATASET}.market_rates` ORDER BY source, rate_type"
    rates = _run_query(sql)
  else:
    sql = f"""
      SELECT * FROM `{PROJECT_ID}.{DATASET}.market_rates`
      WHERE loan_category = @loan_type
      ORDER BY source
    """
    params = [bigquery.ScalarQueryParameter("loan_type", "STRING", loan_type.upper())]
    rates = _run_query(sql, params)

  if not rates:
    return {"error": f"No market rates found for category '{loan_type}'"}

  acme_products = _run_query(
    f"SELECT product_type, product_name, base_rate_percent FROM `{PROJECT_ID}.{DATASET}.products`"
  )
  acme_by_type: dict[str, list[dict]] = {}
  for p in acme_products:
    acme_by_type.setdefault(p["product_type"], []).append(
      {"product": p["product_name"], "rate": p["base_rate_percent"]}
    )

  return {
    "market_rates": rates,
    "acme_rates_by_type": acme_by_type,
    "data_sources": ["Freddie Mac PMMS", "Federal Reserve H.15", "Bankrate Survey"],
    "as_of": datetime.now(timezone.utc).isoformat(),
  }


# ── 2. Model Armor PII redaction ───────────────────────────────────────────


@mcp.tool()
def run_credit_check(customer_id: str) -> dict:
  """Pull a detailed credit report for a customer from the credit bureau.

  ⚠️  SENSITIVE: Returns PII including SSN, date of birth, and full credit
  history. Model Armor at the Agent Gateway automatically detects and redacts
  PII fields before the response reaches the requesting agent.

  This is the primary tool for demonstrating Model Armor's PII redaction
  capabilities within the governance pipeline.

  Args:
    customer_id: The unique identifier for the customer (e.g. 'CUST-001').
  """
  sql = f"SELECT * FROM `{PROJECT_ID}.{DATASET}.customers` WHERE customer_id = @cid"
  params = [bigquery.ScalarQueryParameter("cid", "STRING", customer_id)]
  rows = _run_query(sql, params)
  if not rows:
    return {"error": f"No customer found with id '{customer_id}'"}

  c = rows[0]
  credit_score = c.get("credit_score", 0)

  if credit_score >= 760:
    tier = "EXCELLENT"
  elif credit_score >= 720:
    tier = "GOOD"
  elif credit_score >= 680:
    tier = "FAIR"
  else:
    tier = "POOR"

  return {
    "bureau": "TransUnion",
    "report_id": f"CR-{customer_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
    "subject": {
      "customer_id": customer_id,
      "full_name": c.get("full_name"),
      "ssn": c.get("ssn"),
      "date_of_birth": str(c.get("date_of_birth", "")),
      "address": f"{c.get('address')}, {c.get('city')}, {c.get('state')} {c.get('zip_code')}",
      "phone": c.get("phone"),
      "email": c.get("email"),
      "employer": c.get("employer"),
    },
    "score": {
      "value": credit_score,
      "tier": tier,
      "model": "VantageScore 4.0",
      "range": "300-850",
    },
    "accounts": {
      "total": 12,
      "open": 8,
      "closed": 4,
      "delinquent": 1 if credit_score < 680 else 0,
      "total_balance_usd": 45000 + (800 - credit_score) * 100,
      "available_credit_usd": 25000 + credit_score * 10,
      "oldest_account_years": max(3, (850 - credit_score) // 30),
    },
    "payment_history": {
      "on_time_percent": min(99, 70 + credit_score // 10),
      "late_30_days": 0 if credit_score >= 720 else 1,
      "late_60_days": 0 if credit_score >= 680 else 1,
      "late_90_plus_days": 0,
      "collections": 0,
    },
    "inquiries_last_12_months": max(1, (850 - credit_score) // 50),
    "public_records": [],
    "report_date": datetime.now(timezone.utc).isoformat(),
  }


# ── 3. Sensitive data handling + audit logging ──────────────────────────────


@mcp.tool()
def assess_fraud_risk(application_id: str) -> dict:
  """Run fraud risk assessment on a loan application.

  Analyzes application data against known fraud patterns and produces a
  scored risk profile with detailed indicators. Every invocation is
  audit-logged with a unique trail ID for compliance review.

  This tool accesses sensitive financial data — Agent Gateway enforces
  caller authentication and logs all access for SOX/regulatory audits.

  Args:
    application_id: The loan application ID to assess (e.g. 'APP-2026-001').
  """
  sql = f"SELECT * FROM `{PROJECT_ID}.{DATASET}.applications` WHERE application_id = @aid"
  params = [bigquery.ScalarQueryParameter("aid", "STRING", application_id)]
  rows = _run_query(sql, params)
  if not rows:
    return {"error": f"No application found with id '{application_id}'"}

  app = rows[0]
  risk_score = 0
  indicators = []

  income = float(app.get("annual_income", 0))
  amount = float(app.get("loan_amount", 0))
  dti = float(app.get("dti_ratio", 0))
  credit = int(app.get("credit_score", 0))

  if income > 0 and amount / income > 5:
    risk_score += 25
    indicators.append({
      "rule": "HIGH_LOAN_TO_INCOME",
      "detail": f"Loan amount (${amount:,.0f}) exceeds 5x annual income (${income:,.0f})",
      "severity": "HIGH",
    })

  if dti > 0.43:
    risk_score += 20
    indicators.append({
      "rule": "ELEVATED_DTI",
      "detail": f"DTI ratio {dti:.2f} exceeds QM threshold of 0.43",
      "severity": "HIGH",
    })
  elif dti > 0.38:
    risk_score += 10
    indicators.append({
      "rule": "BORDERLINE_DTI",
      "detail": f"DTI ratio {dti:.2f} approaching QM threshold",
      "severity": "LOW",
    })

  if credit < 620:
    risk_score += 20
    indicators.append({
      "rule": "VERY_LOW_CREDIT",
      "detail": f"Credit score {credit} significantly below minimum (620)",
      "severity": "HIGH",
    })
  elif credit < 660:
    risk_score += 10
    indicators.append({
      "rule": "LOW_CREDIT",
      "detail": f"Credit score {credit} below preferred threshold (660)",
      "severity": "MEDIUM",
    })

  email = app.get("customer_email", "")
  vel_sql = f"SELECT COUNT(*) as cnt FROM `{PROJECT_ID}.{DATASET}.applications` WHERE customer_email = @em"
  vel_params = [bigquery.ScalarQueryParameter("em", "STRING", email)]
  vel_rows = _run_query(vel_sql, vel_params)
  app_count = vel_rows[0]["cnt"] if vel_rows else 0
  if app_count > 2:
    risk_score += 15
    indicators.append({
      "rule": "HIGH_APPLICATION_VELOCITY",
      "detail": f"Customer has {app_count} applications on file",
      "severity": "MEDIUM",
    })

  rate = float(app.get("estimated_rate", 0))
  if rate > 10.0:
    risk_score += 10
    indicators.append({
      "rule": "HIGH_RATE_INDICATOR",
      "detail": f"Estimated rate {rate:.2f}% may indicate high-risk profile",
      "severity": "LOW",
    })

  if risk_score <= 20:
    level = "LOW"
    action = "APPROVE"
  elif risk_score <= 45:
    level = "MEDIUM"
    action = "MANUAL_REVIEW"
  elif risk_score <= 70:
    level = "HIGH"
    action = "ESCALATE"
  else:
    level = "CRITICAL"
    action = "REJECT"

  now = datetime.now(timezone.utc)
  return {
    "application_id": application_id,
    "customer_name": app.get("customer_name"),
    "risk_score": risk_score,
    "risk_level": level,
    "max_possible_score": 100,
    "indicators": indicators,
    "recommendation": action,
    "assessed_at": now.isoformat(),
    "audit_trail_id": f"FRAUD-{application_id}-{now.strftime('%Y%m%d%H%M%S')}",
  }


# ── 4. Policy enforcement guardrails ───────────────────────────────────────

_STATE_RATE_CAPS: dict[str, dict] = {
  "CA": {"max_apr": 10.0, "regulation": "California Finance Lenders Law"},
  "NY": {"max_apr": 16.0, "regulation": "NY Banking Law §14-a"},
  "TX": {"max_apr": 18.0, "regulation": "Texas Finance Code Ch. 303"},
  "FL": {"max_apr": 18.0, "regulation": "FL Statute §687.02"},
  "IL": {"max_apr":  9.0, "regulation": "IL Interest Act 815 ILCS 205/4"},
  "WA": {"max_apr": 12.0, "regulation": "WA Consumer Loan Act"},
  "CO": {"max_apr": 12.0, "regulation": "CO Uniform Consumer Credit Code §5-2-201"},
  "GA": {"max_apr": 16.0, "regulation": "GA Code §7-4-2"},
}

_QM_MAX_DTI = 0.43
_QM_MAX_TERM_YEARS = 30
_QM_MAX_POINTS_PERCENT = 3.0
_HOEPA_RATE_TRIGGER = 6.5  # points above APOR


@mcp.tool()
def check_regulatory_compliance(
  loan_type: str,
  loan_amount: float,
  annual_rate_percent: float,
  loan_term_years: int,
  state: str,
) -> dict:
  """Validate a loan against federal and state regulatory requirements.

  Checks TILA (Truth in Lending Act), HOEPA (Home Ownership and Equity
  Protection Act), Qualified Mortgage rules, and state usury limits.

  Policy enforcement guardrails at the Agent Gateway ensure all loan offers
  pass compliance validation before the agent can present them to a customer.

  Args:
    loan_type: Type of loan — 'MORTGAGE', 'AUTO', 'PERSONAL', or 'HELOC'.
    loan_amount: The loan amount in USD.
    annual_rate_percent: The annual interest rate as a percentage (e.g. 6.5).
    loan_term_years: The loan term in years.
    state: Two-letter state code (e.g. 'CA', 'TX').
  """
  checks = []
  compliant = True
  state_upper = state.upper()
  loan_upper = loan_type.upper()

  state_rule = _STATE_RATE_CAPS.get(state_upper)
  if state_rule:
    passed = annual_rate_percent <= state_rule["max_apr"]
    checks.append({
      "rule": "STATE_USURY_LIMIT",
      "regulation": state_rule["regulation"],
      "threshold": f"{state_rule['max_apr']}% APR",
      "actual": f"{annual_rate_percent}%",
      "passed": passed,
    })
    if not passed:
      compliant = False
  else:
    checks.append({
      "rule": "STATE_USURY_LIMIT",
      "regulation": "No specific state cap on file",
      "threshold": "N/A",
      "actual": f"{annual_rate_percent}%",
      "passed": True,
    })

  if loan_upper in ("MORTGAGE", "HELOC"):
    passed = annual_rate_percent < _HOEPA_RATE_TRIGGER + 6.5
    checks.append({
      "rule": "HOEPA_HIGH_COST_TEST",
      "regulation": "HOEPA — 12 CFR §1026.32",
      "threshold": f"APOR + {_HOEPA_RATE_TRIGGER}% (≈{_HOEPA_RATE_TRIGGER + 6.5}%)",
      "actual": f"{annual_rate_percent}%",
      "passed": passed,
    })
    if not passed:
      compliant = False

  if loan_upper == "MORTGAGE":
    term_ok = loan_term_years <= _QM_MAX_TERM_YEARS
    checks.append({
      "rule": "QM_MAX_TERM",
      "regulation": "Qualified Mortgage Rule — 12 CFR §1026.43(e)",
      "threshold": f"{_QM_MAX_TERM_YEARS} years",
      "actual": f"{loan_term_years} years",
      "passed": term_ok,
    })
    if not term_ok:
      compliant = False

    points_cap = loan_amount * _QM_MAX_POINTS_PERCENT / 100
    checks.append({
      "rule": "QM_POINTS_AND_FEES",
      "regulation": "Qualified Mortgage Rule — 12 CFR §1026.43(e)",
      "threshold": f"≤ {_QM_MAX_POINTS_PERCENT}% of loan (${points_cap:,.0f})",
      "actual": "Assumed compliant (origination fee data not provided)",
      "passed": True,
    })

  checks.append({
    "rule": "TILA_DISCLOSURE",
    "regulation": "Truth in Lending Act — 15 USC §1601",
    "threshold": "APR, finance charge, amount financed, and total payments must be disclosed",
    "actual": "Disclosure required before consummation",
    "passed": True,
  })

  if loan_upper == "MORTGAGE" and loan_amount > 766550:
    checks.append({
      "rule": "CONFORMING_LIMIT",
      "regulation": "FHFA 2026 Conforming Loan Limit",
      "threshold": "$766,550 (single-unit, most areas)",
      "actual": f"${loan_amount:,.0f}",
      "passed": False,
      "note": "Exceeds conforming limit — jumbo underwriting applies",
    })

  return {
    "loan_type": loan_upper,
    "state": state_upper,
    "overall_compliant": compliant,
    "checks": checks,
    "checked_at": datetime.now(timezone.utc).isoformat(),
  }


# ── 5. Write access control ────────────────────────────────────────────────

_VALID_STATUSES = {"APPROVED", "DENIED", "UNDER_REVIEW", "WITHDRAWN", "PENDING_DOCS"}


@mcp.tool()
def update_application_status(
  application_id: str,
  new_status: str,
  notes: str = "",
) -> dict:
  """Update the status of a loan application.

  ⚠️  WRITE OPERATION: This modifies application records in the database.
  Agent Gateway enforces stricter access controls for write operations
  compared to read-only queries — the calling agent must have an elevated
  authorization scope, and all mutations are recorded in the audit log.

  Args:
    application_id: The application ID to update (e.g. 'APP-2026-004').
    new_status: New status — must be one of: APPROVED, DENIED, UNDER_REVIEW,
                WITHDRAWN, PENDING_DOCS.
    notes: Optional notes about the status change.
  """
  status_upper = new_status.upper()
  if status_upper not in _VALID_STATUSES:
    return {
      "error": f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
    }

  check_sql = f"SELECT application_id, status FROM `{PROJECT_ID}.{DATASET}.applications` WHERE application_id = @aid"
  check_params = [bigquery.ScalarQueryParameter("aid", "STRING", application_id)]
  existing = _run_query(check_sql, check_params)
  if not existing:
    return {"error": f"No application found with id '{application_id}'"}

  old_status = existing[0].get("status", "UNKNOWN")

  now = datetime.now(timezone.utc)
  update_notes = f"{notes} [Updated {now.strftime('%Y-%m-%d %H:%M UTC')}]".strip()

  update_sql = f"""
    UPDATE `{PROJECT_ID}.{DATASET}.applications`
    SET status = @new_status,
        notes = @notes,
        decision_date = @decision_date
    WHERE application_id = @aid
  """
  update_params = [
    bigquery.ScalarQueryParameter("new_status", "STRING", status_upper),
    bigquery.ScalarQueryParameter("notes", "STRING", update_notes),
    bigquery.ScalarQueryParameter("decision_date", "STRING", now.strftime("%Y-%m-%d")),
    bigquery.ScalarQueryParameter("aid", "STRING", application_id),
  ]

  affected = _run_dml(update_sql, update_params)

  return {
    "application_id": application_id,
    "previous_status": old_status,
    "new_status": status_upper,
    "notes": update_notes,
    "rows_affected": affected,
    "updated_at": now.isoformat(),
    "audit_trail_id": f"WRITE-{application_id}-{now.strftime('%Y%m%d%H%M%S')}",
  }


# ── 6. Cross-service authorization ─────────────────────────────────────────


@mcp.tool()
def get_property_valuation(zip_code: str, address: str = "") -> dict:
  """Look up property valuation from the external property assessment service.

  Returns estimated market value, comparable sales data, price trends, and
  confidence level for a property. Used for collateral assessment on
  mortgage and HELOC applications.

  Cross-service authorization is enforced — Agent Identity verification
  at the gateway ensures only authorized agents can access third-party
  valuation data from CoreLogic / Zillow APIs.

  Args:
    zip_code: The property ZIP code (required).
    address: Optional street address for a more precise match.
  """
  if address:
    sql = f"""
      SELECT * FROM `{PROJECT_ID}.{DATASET}.property_valuations`
      WHERE zip_code = @zip AND LOWER(address) LIKE LOWER(@addr_pattern)
    """
    params = [
      bigquery.ScalarQueryParameter("zip", "STRING", zip_code),
      bigquery.ScalarQueryParameter("addr_pattern", "STRING", f"%{address}%"),
    ]
  else:
    sql = f"""
      SELECT * FROM `{PROJECT_ID}.{DATASET}.property_valuations`
      WHERE zip_code = @zip
    """
    params = [bigquery.ScalarQueryParameter("zip", "STRING", zip_code)]

  rows = _run_query(sql, params)
  if not rows:
    return {"error": f"No property valuations found for ZIP '{zip_code}'"}

  for row in rows:
    est = row.get("estimated_value", 0)
    last = row.get("last_sale_price", 0)
    if last and est:
      row["appreciation_pct"] = round((est - last) / last * 100, 1)
    row["max_ltv_recommended"] = 80 if row.get("confidence") == "HIGH" else 70

  return {
    "properties": rows,
    "valuation_provider": "CoreLogic AVM",
    "retrieved_at": datetime.now(timezone.utc).isoformat(),
  }


# ── Server entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
  import uvicorn
  port = int(os.environ.get("PORT", "8080"))
  app = mcp.streamable_http_app()
  uvicorn.run(app, host="0.0.0.0", port=port)
