#!/usr/bin/env bash
set -euo pipefail

PROJECT="privacy-ml-lab1"
REGION="us-central1"
BACKEND_SERVICE="loan-advisor-backend"
UI_SERVICE="loan-advisor-ui"
SA="190206934161-compute@developer.gserviceaccount.com"

echo "=== Deploying Loan Advisor to Cloud Run ==="
echo "Project: $PROJECT | Region: $REGION"
echo ""

# --- 1. Deploy backend ---
echo "--- Step 1: Deploying backend ($BACKEND_SERVICE) ---"
gcloud run deploy "$BACKEND_SERVICE" \
  --source ui/backend \
  --project "$PROJECT" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --service-account "$SA" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "CORS_ORIGINS=*"

BACKEND_URL=$(gcloud run services describe "$BACKEND_SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)')
echo ""
echo "Backend deployed: $BACKEND_URL"
echo ""

# --- 2. Deploy frontend + runtime ---
echo "--- Step 2: Deploying UI ($UI_SERVICE) ---"
gcloud run deploy "$UI_SERVICE" \
  --source ui \
  --project "$PROJECT" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "AG_UI_BACKEND_URL=$BACKEND_URL,AGENT_NAME=loan_advisor"

UI_URL=$(gcloud run services describe "$UI_SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)')
echo ""
echo "=========================================="
echo "Deployment complete!"
echo ""
echo "  UI:      $UI_URL"
echo "  Backend: $BACKEND_URL"
echo ""
echo "NOTE: To enable OAuth flow, update the agent's"
echo "CONTINUE_URI to: $UI_URL"
echo "and redeploy the agent to Agent Engine."
echo "=========================================="
