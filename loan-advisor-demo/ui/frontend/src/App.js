import { useEffect, useRef, useState, useCallback } from "react";
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
  { icon: "cable", label: "MCP Server", status: "Connected", color: "#34a853" },
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
  const resuming = useRef(false);
  const cookiesSet = useRef(false);

  useEffect(() => {
    // Watch for auth links in the DOM and set cookies when one appears
    const observer = new MutationObserver(() => {
      if (cookiesSet.current) return;
      const authLink = document.querySelector('a[href*="accounts.google.com"]');
      if (authLink) {
        cookiesSet.current = true;
        fetch(`${BACKEND_URL}/auth-nonce`, { credentials: "include" })
          .then(() => console.log("Auth cookies set"))
          .catch(() => {});
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    const handler = async (event) => {
      if (event.data?.type !== "AUTH_COMPLETE" || resuming.current) return;
      resuming.current = true;
      cookiesSet.current = false;

      appendMessage({
        id: `auth-ok-${Date.now()}`,
        role: "assistant",
        content:
          "✅ **Authorization successful!** Your credentials have been securely stored via Agent Identity.\n\nPlease repeat your request and I'll access your data.",
      });

      resuming.current = false;
    };

    window.addEventListener("message", handler);
    return () => {
      window.removeEventListener("message", handler);
      observer.disconnect();
    };
  }, [appendMessage]);

  return null;
}

/* ── Config ─────────────────────────────────────────────────────────────── */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const RUNTIME_URL =
  process.env.REACT_APP_COPILOT_RUNTIME_URL || "/api/copilotkit";

/* ── Main App ───────────────────────────────────────────────────────────── */

function App() {
  const agent = process.env.REACT_APP_COPILOT_AGENT || "loan_advisor";
  const [armorRequest, setArmorRequest] = useState(false);
  const [armorResponse, setArmorResponse] = useState(false);
  const [causalArmor, setCausalArmor] = useState(false);
  const [causalLogs, setCausalLogs] = useState([]);
  const [showCausalLogs, setShowCausalLogs] = useState(false);
  const [users, setUsers] = useState([]);
  const [activeUser, setActiveUser] = useState("");

  useEffect(() => {
    fetch(`${BACKEND_URL}/model-armor/config`)
      .then((r) => r.json())
      .then((d) => {
        setArmorRequest(d.request || false);
        setArmorResponse(d.response || false);
      })
      .catch(() => {});
    fetch(`${BACKEND_URL}/causal-armor/config`)
      .then((r) => r.json())
      .then((d) => setCausalArmor(d.enabled || false))
      .catch(() => {});
    fetch(`${BACKEND_URL}/users`)
      .then((r) => r.json())
      .then((d) => {
        setUsers(d.users || []);
        setActiveUser(d.active || "");
      })
      .catch(() => {});
  }, []);

  const toggleArmor = useCallback(async (field, value) => {
    try {
      const resp = await fetch(`${BACKEND_URL}/model-armor/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      });
      const d = await resp.json();
      setArmorRequest(d.request || false);
      setArmorResponse(d.response || false);
    } catch (e) { /* ignore */ }
  }, []);

  const toggleCausalArmor = useCallback(async (value) => {
    setCausalArmor(value);
    try {
      await fetch(`${BACKEND_URL}/causal-armor/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: value }),
      });
    } catch (e) { /* ignore */ }
  }, []);

  const fetchCausalLogs = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/causal-armor/logs`);
      const d = await resp.json();
      setCausalLogs(d.logs || []);
      setShowCausalLogs(true);
    } catch (e) { /* ignore */ }
  }, []);

  return (
    <CopilotKit agent={agent} runtimeUrl={RUNTIME_URL}>
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

          {/* User selector */}
          {users.length > 0 && (
            <div style={{ padding: "12px 20px" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#5f6368", textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 6 }}>
                Signed in as
              </div>
              <select
                value={activeUser}
                onChange={async (e) => {
                  const uid = e.target.value;
                  setActiveUser(uid);
                  try {
                    await fetch(`${BACKEND_URL}/users/active`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ user_id: uid }),
                    });
                  } catch (err) { /* ignore */ }
                }}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid #c5d9f9",
                  background: "#e8f0fe",
                  fontSize: 12,
                  fontWeight: 600,
                  color: "#1a73e8",
                  cursor: "pointer",
                  outline: "none",
                  fontFamily: "inherit",
                }}
              >
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.role})
                  </option>
                ))}
              </select>
            </div>
          )}

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

            {/* Model Armor Toggles */}
            <div
              style={{
                marginTop: 16,
                padding: "12px",
                borderRadius: 12,
                background: "#fff",
                border: "1px solid #e1e3e1",
              }}
            >
              <div style={{ fontSize: 10, fontWeight: 700, color: "#5f6368", textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 10 }}>
                Model Armor Policies
              </div>
              {[
                { label: "Request Scanning", desc: "Prompt injection detection", field: "request", value: armorRequest, setter: setArmorRequest, icon: "login" },
                { label: "Response Scanning", desc: "PII / unsafe content", field: "response", value: armorResponse, setter: setArmorResponse, icon: "logout" },
              ].map((t) => (
                <div key={t.field} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0" }}>
                  <span className="material-icons-outlined" style={{ fontSize: 16, color: t.value ? "#34a853" : "#9aa0a6" }}>{t.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#1f1f1f" }}>{t.label}</div>
                    <div style={{ fontSize: 10, color: "#5f6368" }}>{t.desc}</div>
                  </div>
                  <label style={{ position: "relative", width: 36, height: 20, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={t.value}
                      onChange={(e) => {
                        t.setter(e.target.checked);
                        toggleArmor(t.field, e.target.checked);
                      }}
                      style={{ display: "none" }}
                    />
                    <span style={{
                      position: "absolute", inset: 0, borderRadius: 10,
                      background: t.value ? "#34a853" : "#dadce0",
                      transition: "background 0.2s",
                    }} />
                    <span style={{
                      position: "absolute", top: 2, left: t.value ? 18 : 2,
                      width: 16, height: 16, borderRadius: "50%",
                      background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                      transition: "left 0.2s",
                    }} />
                  </label>
                </div>
              ))}

              {/* Causal Armor Toggle */}
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #f0f0f0" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0" }}>
                  <span className="material-icons-outlined" style={{ fontSize: 16, color: causalArmor ? "#9334e6" : "#9aa0a6" }}>science</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#1f1f1f" }}>Causal Armor</div>
                    <div style={{ fontSize: 10, color: "#5f6368" }}>LOO prompt injection detection</div>
                  </div>
                  <label style={{ position: "relative", width: 36, height: 20, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={causalArmor}
                      onChange={(e) => toggleCausalArmor(e.target.checked)}
                      style={{ display: "none" }}
                    />
                    <span style={{
                      position: "absolute", inset: 0, borderRadius: 10,
                      background: causalArmor ? "#9334e6" : "#dadce0",
                      transition: "background 0.2s",
                    }} />
                    <span style={{
                      position: "absolute", top: 2, left: causalArmor ? 18 : 2,
                      width: 16, height: 16, borderRadius: "50%",
                      background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                      transition: "left 0.2s",
                    }} />
                  </label>
                </div>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#9aa0a6", textTransform: "uppercase", letterSpacing: 1, marginTop: 8, marginBottom: 4 }}>
                  Test IPI
                </div>
                {[
                  { step: "1", text: "Look up customer CUST-003" },
                  { step: "2", text: "Are there any pending actions for this customer?" },
                ].map((t) => (
                  <div
                    key={t.step}
                    onClick={() => navigator.clipboard.writeText(t.text)}
                    title="Click to copy"
                    style={{
                      fontSize: 10, color: "#5f6368", padding: "3px 0",
                      cursor: "pointer", display: "flex", gap: 4,
                    }}
                  >
                    <span style={{ color: "#9334e6", fontWeight: 700, fontSize: 9 }}>{t.step}.</span>
                    <span style={{ fontStyle: "italic" }}>{t.text}</span>
                  </div>
                ))}
                <button
                  onClick={fetchCausalLogs}
                  style={{
                    width: "100%", marginTop: 6, padding: "6px 0",
                    borderRadius: 8, border: "1px solid #e0d4f5",
                    background: "#f3e8ff", color: "#7c3aed",
                    fontSize: 11, fontWeight: 600, cursor: "pointer",
                    fontFamily: "inherit",
                  }}
                >
                  View LOO Analysis Logs
                </button>
              </div>
            </div>

            {/* Causal Armor Log Panel */}
            {showCausalLogs && (
              <div style={{
                margin: "0 16px 12px", padding: 12, borderRadius: 12,
                background: "#faf5ff", border: "1px solid #e0d4f5",
                maxHeight: 300, overflowY: "auto",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#7c3aed", textTransform: "uppercase", letterSpacing: 1.5 }}>
                    LOO Analysis Log
                  </div>
                  <span
                    className="material-icons-outlined"
                    style={{ fontSize: 14, color: "#9aa0a6", cursor: "pointer" }}
                    onClick={() => setShowCausalLogs(false)}
                  >close</span>
                </div>
                {causalLogs.length === 0 && (
                  <div style={{ fontSize: 11, color: "#5f6368", fontStyle: "italic" }}>No Causal Armor events found.</div>
                )}
                {causalLogs.map((log, i) => (
                  <div key={i} style={{
                    padding: "8px 10px", marginBottom: 6, borderRadius: 8,
                    background: log.action === "BLOCKED" ? "#fef2f2" : "#f0fdf4",
                    border: `1px solid ${log.action === "BLOCKED" ? "#fecaca" : "#bbf7d0"}`,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
                        background: log.action === "BLOCKED" ? "#dc2626" : "#16a34a",
                        color: "#fff", textTransform: "uppercase", letterSpacing: 0.5,
                      }}>{log.action}</span>
                      <span style={{ fontSize: 11, fontWeight: 600, color: "#1f1f1f", fontFamily: "var(--font-mono)" }}>
                        {log.tool}
                      </span>
                      <span style={{ fontSize: 9, color: "#9aa0a6", marginLeft: "auto" }}>
                        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ""}
                      </span>
                    </div>
                    <div style={{ fontSize: 10, color: "#444746", fontFamily: "var(--font-mono)" }}>
                      <span style={{ color: "#5f6368" }}>user_delta:</span>{" "}
                      <span style={{ fontWeight: 600 }}>{log.user_delta?.toFixed(4) ?? "N/A"}</span>
                      {log.span_deltas && Object.entries(log.span_deltas).map(([k, v]) => (
                        <span key={k}>
                          {" | "}<span style={{ color: "#5f6368" }}>{k.split(":")[0]}:</span>{" "}
                          <span style={{ fontWeight: 600, color: v > 2 ? "#dc2626" : "#1f1f1f" }}>{v.toFixed(4)}</span>
                        </span>
                      ))}
                    </div>
                    {log.flagged_spans && (
                      <div style={{ fontSize: 10, color: "#dc2626", marginTop: 2 }}>
                        Flagged: {log.flagged_spans}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
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
