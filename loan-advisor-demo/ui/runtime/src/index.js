import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";
import { CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotExpressHandler } from "@copilotkit/runtime/v2/express";
import { HttpAgent } from "@ag-ui/client";
import { createProxyMiddleware } from "http-proxy-middleware";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || "4002");
const backendUrl = process.env.AG_UI_BACKEND_URL || "http://localhost:8888";
const agentName = process.env.AGENT_NAME || "loan_advisor";

const agUiAgent = new HttpAgent({ url: `${backendUrl}/agent` });

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
  res.json({ status: "healthy", backend: backendUrl, agentName });
});

const proxyPrefixes = ["/agent", "/auth-nonce", "/commit", "/model-armor", "/users", "/resume-result"];
app.use(
  createProxyMiddleware({
    target: backendUrl,
    changeOrigin: true,
    pathFilter: (pathname) =>
      proxyPrefixes.some((p) => pathname === p || pathname.startsWith(p + "/")),
  })
);

const publicDir = path.join(__dirname, "..", "public");
app.use(express.static(publicDir));
app.get("*", (_req, res, next) => {
  const indexPath = path.join(publicDir, "index.html");
  res.sendFile(indexPath, (err) => {
    if (err) next();
  });
});

app.listen(PORT, () => {
  console.log(`Loan Advisor UI on port ${PORT}`);
  console.log(`  CopilotKit: /api/copilotkit`);
  console.log(`  Backend proxy -> ${backendUrl}`);
});
