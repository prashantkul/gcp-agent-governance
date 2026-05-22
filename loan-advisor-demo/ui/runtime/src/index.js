/**
 * CopilotKit Runtime Service for Loan Advisor
 *
 * Express server that provides a CopilotKit runtime endpoint,
 * proxying requests to the AG-UI backend (FastAPI + ADK).
 */

import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNodeHttpEndpoint,
} from '@copilotkit/runtime';
import { HttpAgent } from '@ag-ui/client';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 4000;
const NODE_ENV = process.env.NODE_ENV || 'development';

const corsOrigins = process.env.CORS_ORIGINS
  ? process.env.CORS_ORIGINS.split(',').map((o) => o.trim())
  : ['http://localhost:3000'];

app.use(
  cors({
    origin: corsOrigins,
    credentials: true,
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: [
      'Content-Type',
      'Authorization',
      'x-copilotkit-runtime-client-gql-version',
      'x-copilotkit-frontend-url',
      'x-copilotkit-request-id',
      'x-copilotkit-thread-id',
      'x-copilotkit-run-id',
    ],
  })
);

app.use(express.json());

// -- AG-UI HttpAgent pointing at the Python backend --
const agentUrl = process.env.AG_UI_AGENT_URL || 'http://localhost:8888/agent';
const agentName = process.env.AGENT_NAME || 'loan_advisor';

const agUiAgent = new HttpAgent({ url: agentUrl });

const runtime = new CopilotRuntime({
  agents: { [agentName]: agUiAgent },
});

// -- CopilotKit runtime endpoint --
const runtimeEndpoint = '/api/copilotkit';

const copilotRuntime = copilotRuntimeNodeHttpEndpoint({
  runtime,
  serviceAdapter: new ExperimentalEmptyAdapter(),
  endpoint: runtimeEndpoint,
});

app.use(runtimeEndpoint, async (req, res) => {
  return copilotRuntime(req, res);
});

// -- Health & info --
app.get('/health', (_req, res) => {
  res.json({
    status: 'healthy',
    service: 'loan-advisor-copilotkit-runtime',
    timestamp: new Date().toISOString(),
    agentUrl,
    agentName,
  });
});

app.get('/', (_req, res) => {
  res.json({
    message: 'Loan Advisor CopilotKit Runtime',
    version: '1.0.0',
    endpoints: { runtime: runtimeEndpoint, health: '/health' },
    agent: { name: agentName, url: agentUrl },
  });
});

// -- Error handling --
app.use((err, _req, res, _next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Internal Server Error' });
});

app.use((_req, res) => {
  res.status(404).json({ error: 'Not Found' });
});

// -- Start --
app.listen(PORT, () => {
  console.log(`CopilotKit Runtime running on port ${PORT}`);
  console.log(`  Runtime endpoint: http://localhost:${PORT}${runtimeEndpoint}`);
  console.log(`  AG-UI agent URL:  ${agentUrl}`);
  console.log(`  Health check:     http://localhost:${PORT}/health`);
});

export default app;
