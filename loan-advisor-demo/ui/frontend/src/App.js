import { CopilotKit } from "@copilotkit/react-core";
import "@copilotkit/react-ui/styles.css";
import { CopilotChat } from "@copilotkit/react-ui";

function App() {
  const runtimeUrl =
    process.env.REACT_APP_COPILOT_RUNTIME_URL ||
    "http://localhost:4000/api/copilotkit";
  const agent = process.env.REACT_APP_COPILOT_AGENT || "loan_advisor";

  return (
    <CopilotKit agent={agent} runtimeUrl={runtimeUrl}>
      <div
        style={{
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          background: "#f7f8fa",
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: "16px 24px",
            background: "#1a365d",
            color: "white",
            display: "flex",
            alignItems: "center",
            gap: "12px",
            boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
          }}
        >
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              background: "#e2e8f0",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: "bold",
              color: "#1a365d",
              fontSize: 18,
            }}
          >
            A
          </div>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 600 }}>
              Acme Financial Services
            </h1>
            <p style={{ fontSize: 12, opacity: 0.8 }}>Loan Advisor</p>
          </div>
        </header>

        {/* Chat area */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          <CopilotChat
            instructions="You are the Acme Financial Services Loan Advisor. Help customers check loan eligibility, estimate interest rates, and explore loan products."
            labels={{
              title: "Loan Advisor",
              initial:
                "Welcome to Acme Financial Services! I can help you check loan eligibility, estimate rates, and look up loan products. How can I help you today?",
            }}
          />
        </div>
      </div>
    </CopilotKit>
  );
}

export default App;
