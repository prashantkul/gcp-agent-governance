import { useEffect, useRef } from "react";
import { CopilotKit, useCopilotChat } from "@copilotkit/react-core";
import "@copilotkit/react-ui/styles.css";
import { CopilotChat } from "@copilotkit/react-ui";

/* ── Data ───────────────────────────────────────────────────────────────── */

const SUGGESTIONS = [
  {
    icon: "trending_up",
    label: "Eligibility",
    text: "Am I eligible for a $400K mortgage? I earn $120K, score 755",
    color: "#4285f4",
    bg: "#d2e3fc",
  },
  {
    icon: "account_balance",
    label: "Products",
    text: "What loan products do you offer?",
    color: "#ea4335",
    bg: "#fad2cf",
  },
  {
    icon: "query_stats",
    label: "Applications",
    text: "Show all pending loan applications",
    color: "#34a853",
    bg: "#ceead6",
  },
  {
    icon: "person_search",
    label: "Customer",
    text: "Look up customer CUST-001",
    color: "#9334e6",
    bg: "#e9d5ff",
  },
];

const GOVERNANCE = [
  { icon: "fingerprint", label: "Agent Identity", status: "Active", color: "#34a853" },
  { icon: "shield", label: "Model Armor", status: "Enforcing", color: "#34a853" },
  { icon: "hub", label: "Agent Registry", status: "Registered", color: "#4285f4" },
  { icon: "security", label: "Agent Gateway", status: "Preview", color: "#fbbc04" },
];

/* ── AI avatar SVG ──────────────────────────────────────────────────────── */

function AIAvatar({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" fill="none">
      <defs>
        <linearGradient id="aiGrad" x1="0" y1="0" x2="36" y2="36">
          <stop offset="0%" stopColor="#4285f4" />
          <stop offset="100%" stopColor="#34a853" />
        </linearGradient>
      </defs>
      <rect width="36" height="36" rx="10" fill="url(#aiGrad)" />
      <circle cx="13" cy="15" r="2.5" fill="#fff" opacity="0.9" />
      <circle cx="23" cy="15" r="2.5" fill="#fff" opacity="0.9" />
      <path
        d="M12 22c0 0 2.5 4 6 4s6-4 6-4"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.9"
        fill="none"
      />
      <rect x="7" y="5" width="4" height="2" rx="1" fill="#fff" opacity="0.4" />
      <rect x="25" y="5" width="4" height="2" rx="1" fill="#fff" opacity="0.4" />
    </svg>
  );
}

/* ── Auth Resume Listener ───────────────────────────────────────────────── */

function AuthResumeListener() {
  const { appendMessage } = useCopilotChat();
  const polling = useRef(false);

  useEffect(() => {
    const handler = async (event) => {
      if (event.data?.type !== "AUTH_COMPLETE" || polling.current) return;
      polling.current = true;

      // Poll for resume result
      for (let i = 0; i < 60; i++) {
        try {
          const resp = await fetch("http://localhost:8888/resume-result");
          const data = await resp.json();
          if (data.status === "complete" && data.result) {
            appendMessage({
              id: Date.now().toString(),
              role: "assistant",
              content: data.result,
            });
            polling.current = false;
            return;
          }
        } catch (e) { /* ignore */ }
        await new Promise((r) => setTimeout(r, 1000));
      }
      polling.current = false;
    };

    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [appendMessage]);

  return null;
}

/* ── Main App ───────────────────────────────────────────────────────────── */

function App() {
  const runtimeUrl =
    process.env.REACT_APP_COPILOT_RUNTIME_URL ||
    "http://localhost:4002/api/copilotkit";
  const agent = process.env.REACT_APP_COPILOT_AGENT || "loan_advisor";

  return (
    <CopilotKit agent={agent} runtimeUrl={runtimeUrl}>
      <AuthResumeListener />
      <div style={{ display: "flex", height: "100vh", background: "#f8f9fa" }}>
        {/* ── Sidebar ─────────────────────────────────────────────── */}
        <aside
          style={{
            width: 304,
            display: "flex",
            flexDirection: "column",
            background: "#fff",
            borderRight: "1px solid #e1e3e1",
          }}
        >
          {/* Gradient strip */}
          <div className="acme-gradient-strip" />

          {/* Brand header */}
          <div
            style={{
              padding: "20px 20px 16px",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            {/* Logo mark */}
            <div
              style={{
                width: 42,
                height: 42,
                borderRadius: 12,
                background:
                  "linear-gradient(135deg, #4285f4 0%, #34a853 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                boxShadow: "0 2px 8px rgba(66,133,244,0.25)",
              }}
            >
              <span
                className="material-icons-outlined"
                style={{ fontSize: 24, color: "#fff" }}
              >
                account_balance
              </span>
            </div>
            <div>
              <div
                style={{
                  fontFamily: "'Righteous', cursive",
                  fontSize: 19,
                  color: "#1f1f1f",
                  lineHeight: 1.1,
                  letterSpacing: "0.01em",
                }}
              >
                Acme Financial
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "#444746",
                  fontWeight: 500,
                  marginTop: 2,
                }}
              >
                Loan Advisor
              </div>
            </div>
          </div>

          <div style={{ height: 1, background: "#e1e3e1", margin: "0 20px" }} />

          {/* Suggestions */}
          <div style={{ padding: "16px 16px 8px", flex: 1, overflow: "auto" }}>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: "#444746",
                textTransform: "uppercase",
                letterSpacing: 1.5,
                padding: "0 4px",
                marginBottom: 12,
              }}
            >
              Try asking
            </div>
            {SUGGESTIONS.map((s, i) => (
              <div
                key={i}
                className="suggestion-card"
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  padding: "12px 14px",
                  marginBottom: 6,
                  borderRadius: 14,
                  border: "1px solid #e1e3e1",
                  cursor: "pointer",
                  background: "#fff",
                }}
              >
                <div
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: 10,
                    background: s.bg,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <span
                    className="material-icons-outlined"
                    style={{ fontSize: 18, color: s.color }}
                  >
                    {s.icon}
                  </span>
                </div>
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: s.color,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                      marginBottom: 2,
                    }}
                  >
                    {s.label}
                  </div>
                  <div
                    style={{
                      fontSize: 12.5,
                      color: "#444746",
                      lineHeight: 1.45,
                      fontWeight: 500,
                    }}
                  >
                    {s.text}
                  </div>
                </div>
              </div>
            ))}

            {/* Divider */}
            <div
              style={{
                height: 1,
                background: "#e1e3e1",
                margin: "16px 4px",
              }}
            />

            {/* Governance */}
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: "#444746",
                textTransform: "uppercase",
                letterSpacing: 1.5,
                padding: "0 4px",
                marginBottom: 12,
              }}
            >
              Governance
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {GOVERNANCE.map((g, i) => (
                <div
                  key={i}
                  className={
                    g.status !== "Preview" ? "gov-badge-active" : undefined
                  }
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 12px",
                    borderRadius: 10,
                    background:
                      g.status === "Preview"
                        ? "#fffbeb"
                        : g.color === "#4285f4"
                          ? "#e8f0fe"
                          : "#e6f4ea",
                    border: `1px solid ${
                      g.status === "Preview"
                        ? "#fde68a"
                        : g.color === "#4285f4"
                          ? "#c5d9f9"
                          : "#a8dab5"
                    }`,
                  }}
                >
                  <span
                    className="material-icons-outlined"
                    style={{ fontSize: 16, color: g.color }}
                  >
                    {g.icon}
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#1f1f1f",
                      flex: 1,
                    }}
                  >
                    {g.label}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      color: g.color,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {g.status}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div
            style={{
              padding: "14px 20px",
              borderTop: "1px solid #e1e3e1",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24">
              <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                fill="#4285F4"
              />
              <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
              />
              <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                fill="#EA4335"
              />
            </svg>
            <span
              style={{ fontSize: 11, color: "#444746", fontWeight: 500 }}
            >
              ADK 2.0
            </span>
            <span style={{ fontSize: 11, color: "#c4c7c5" }}>·</span>
            <span
              style={{ fontSize: 11, color: "#444746", fontWeight: 500 }}
            >
              Gemini 2.5 Flash
            </span>
          </div>
        </aside>

        {/* ── Main area ───────────────────────────────────────────── */}
        <main
          style={{ flex: 1, display: "flex", flexDirection: "column" }}
        >
          {/* Top bar */}
          <div className="acme-gradient-strip" />
          <header
            style={{
              padding: "12px 28px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "#fff",
              borderBottom: "1px solid #e1e3e1",
            }}
          >
            <div
              style={{ display: "flex", alignItems: "center", gap: 14 }}
            >
              <AIAvatar size={38} />
              <div>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: "#1f1f1f",
                    letterSpacing: "-0.01em",
                  }}
                >
                  Loan Advisor
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    marginTop: 1,
                  }}
                >
                  <div
                    className="pulse-dot"
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: "50%",
                      background: "#34a853",
                    }}
                  />
                  <span style={{ fontSize: 11, color: "#444746" }}>
                    Online
                  </span>
                  <span style={{ fontSize: 11, color: "#c4c7c5" }}>
                    ·
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      color: "#444746",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    gemini-2.5-flash
                  </span>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {/* Security badge */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 14px",
                  borderRadius: 20,
                  background: "#e6f4ea",
                  border: "1px solid #a8dab5",
                }}
              >
                <span
                  className="material-icons-outlined"
                  style={{ fontSize: 14, color: "#137333" }}
                >
                  verified_user
                </span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: "#137333",
                    letterSpacing: "0.02em",
                  }}
                >
                  AGENT IDENTITY SECURED
                </span>
              </div>
            </div>
          </header>

          {/* Chat */}
          <div style={{ flex: 1, overflow: "hidden", background: "#fff" }}>
            <CopilotChat
              instructions="You are the Acme Financial Services Loan Advisor. Help customers check loan eligibility, estimate interest rates, query loan data, and explore products. Be professional and concise."
              labels={{
                title: "Loan Advisor",
                initial:
                  "Welcome to Acme Financial Services!\n\nI'm your AI-powered Loan Advisor. I can help you with:\n\n• **Check eligibility** — income, credit score, loan amount\n• **Estimate rates** — monthly payments, total cost\n• **Browse products** — mortgages, auto, personal, HELOC\n• **Look up data** — applications, customer profiles\n\nWhat would you like to explore?",
              }}
            />
          </div>
        </main>
      </div>
    </CopilotKit>
  );
}

export default App;
