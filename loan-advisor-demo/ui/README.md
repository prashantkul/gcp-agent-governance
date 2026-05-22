# Loan Advisor - CopilotKit (AG-UI) Frontend

A 3-layer architecture that connects the Loan Advisor ADK agent to a React chat
UI via the AG-UI protocol and CopilotKit.

```
React Frontend  -->  CopilotKit Runtime (Node.js)  -->  AG-UI Backend (FastAPI/ADK)
   :3000                   :4000                              :8888
```

## Architecture

| Layer | Directory | Port | Purpose |
|-------|-----------|------|---------|
| Backend | `ui/backend/` | 8888 | Bridges the ADK agent to the AG-UI protocol |
| Runtime | `ui/runtime/` | 4000 | CopilotKit runtime that routes to the AG-UI backend |
| Frontend | `ui/frontend/` | 3000 | React app with CopilotKit chat UI |

## Prerequisites

- Python 3.11+ with `uv`
- Node.js 18+
- Google Cloud credentials configured (for the ADK agent)

## Running

Start each layer in a separate terminal, from the **project root**
(`loan-advisor-demo/`).

### 1. Backend (Python/FastAPI)

```bash
cd ui/backend
uv sync
cd src
uv run python main.py
```

The AG-UI endpoint will be available at `http://localhost:8888/agent`.

### 2. Runtime (Node.js)

```bash
cd ui/runtime
cp .env.example .env   # adjust if needed
npm install
npm run dev
```

The CopilotKit runtime will be available at `http://localhost:4000/api/copilotkit`.

### 3. Frontend (React)

```bash
cd ui/frontend
npm install
npm start
```

Opens `http://localhost:3000` in the browser.

## Environment Variables

### Backend (`ui/backend/`)

Uses the same environment variables as the main Loan Advisor app (Google Cloud
credentials, `GOOGLE_CLOUD_PROJECT`, etc.). Additionally:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `0.0.0.0` | Server bind host |
| `SERVER_PORT` | `8888` | Server port |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:4000` | Allowed CORS origins |

### Runtime (`ui/runtime/`)

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `4000` | Runtime server port |
| `AG_UI_AGENT_URL` | `http://localhost:8888/agent` | URL of the AG-UI backend |
| `AGENT_NAME` | `loan_advisor` | Agent name registered in the runtime |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |

### Frontend (`ui/frontend/`)

| Variable | Default | Description |
|----------|---------|-------------|
| `REACT_APP_COPILOT_RUNTIME_URL` | `http://localhost:4000/api/copilotkit` | CopilotKit runtime URL |
| `REACT_APP_COPILOT_AGENT` | `loan_advisor` | Agent name to use |
