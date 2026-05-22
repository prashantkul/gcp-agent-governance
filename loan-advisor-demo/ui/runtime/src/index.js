import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import { CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotExpressHandler } from "@copilotkit/runtime/v2/express";
import { HttpAgent } from "@ag-ui/client";

dotenv.config();

const PORT = parseInt(process.env.PORT || "4002");
const agentUrl = process.env.AG_UI_AGENT_URL || "http://localhost:8888/agent";
const agentName = process.env.AGENT_NAME || "loan_advisor";

const agUiAgent = new HttpAgent({ url: agentUrl });

const runtime = new CopilotRuntime({
  agents: { [agentName]: agUiAgent },
});

const app = express();
app.use(cors({ origin: true, credentials: true }));

app.use(
  createCopilotExpressHandler({
    runtime,
    basePath: "/api/copilotkit",
    mode: "single-route",
    cors: true,
  })
);

app.get("/health", (_req, res) => {
  res.json({ status: "healthy", agentUrl, agentName });
});

app.listen(PORT, () => {
  console.log(`CopilotKit Runtime on http://localhost:${PORT}`);
  console.log(`  Endpoint: http://localhost:${PORT}/api/copilotkit`);
  console.log(`  AG-UI agent: ${agentUrl}`);
});
