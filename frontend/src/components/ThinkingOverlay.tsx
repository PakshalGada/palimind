import { useState } from "react";
import { useApp } from "../AppContext";
import { ThinkingOrb } from "thinking-orbs";

const AGENT_BADGES = ["1", "2", "3", "4"];

const DEFAULT_AGENTS = [
  {
    agent_id: 1,
    label: "Researcher (Web Search)",
    task: "Searching web for live information...",
    status: "working",
    steps: ["Querying web engines..."],
  },
  {
    agent_id: 2,
    label: "Specialist Agent 2",
    task: "Orchestrator creating task plan...",
    status: "working",
    steps: [],
  },
  {
    agent_id: 3,
    label: "Specialist Agent 3",
    task: "Orchestrator creating task plan...",
    status: "working",
    steps: [],
  },
  {
    agent_id: 4,
    label: "Specialist Agent 4",
    task: "Orchestrator creating task plan...",
    status: "working",
    steps: [],
  },
];

export default function ThinkingOverlay() {
  const { isGenerating, thinkingText, agentStates, chatMode, llmSubMode } = useApp();
  const [isCollapsed, setIsCollapsed] = useState(false);

  try {
    if (!isGenerating) return null;

    const isMoeActive = (chatMode === "llm" && llmSubMode === "moe") || agentStates.length > 0;

    if (!isMoeActive) {
      const modeTitle = chatMode === "document" ? "Document Mode" : "LLM Mode";
      return (
        <div className="thinking-overlay">
          <div className="moe-single-card">
            <div className="moe-card-header" style={{ borderBottom: "none", paddingBottom: 0 }}>
              <div className="moe-card-header-left">
                <ThinkingOrb
                  state="solving"
                  size={20}
                  style={{ background: "transparent" }}
                />
                <span className="moe-card-title">{modeTitle}</span>
              </div>
              {thinkingText && (
                <span className="moe-card-status-text">{thinkingText}</span>
              )}
            </div>
          </div>
        </div>
      );
    }

    const displayAgentStates =
      agentStates.length > 0 ? agentStates : DEFAULT_AGENTS;

    const workingAgents = displayAgentStates.filter((a: any) => a.status === "working");

    return (
      <div className="thinking-overlay">
        <div className="moe-single-card">
          <div className="moe-card-header">
            <div className="moe-card-header-left">
              <ThinkingOrb
                state="solving"
                size={20}
                style={{ background: "transparent" }}
              />
              <span className="moe-card-title">Mixture of Experts</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {thinkingText && (
                <span className="moe-card-status-text">{thinkingText}</span>
              )}
              <button
                className="moe-collapse-toggle-btn"
                onClick={() => setIsCollapsed(!isCollapsed)}
                title={isCollapsed ? "Expand thinking" : "Collapse thinking"}
              >
                {isCollapsed ? "Show Full Thinking ▼" : "Collapse ▲"}
              </button>
            </div>
          </div>

          {!isCollapsed ? (
            <div className="moe-agents-list">
              {displayAgentStates.map((agent: any) => {
                const isWebSearchAgent =
                  agent.agent_id === 1 ||
                  agent.label?.toLowerCase().includes("search") ||
                  agent.label?.toLowerCase().includes("research");
                return (
                  <div
                    key={agent.agent_id}
                    className={`moe-agent-row ${agent.status}`}
                  >
                    <div className="moe-agent-row-header">
                      <span className="moe-agent-badge">
                        {AGENT_BADGES[(agent.agent_id - 1) % 4] || agent.agent_id}
                      </span>
                      <div className="moe-agent-info">
                        <span className="moe-agent-label">
                          {agent.label || `Agent ${agent.agent_id}`}
                        </span>
                        {agent.task && (
                          <span className="moe-agent-task">{agent.task}</span>
                        )}
                      </div>
                      <span className={`moe-agent-status ${agent.status}`}>
                        {agent.status === "working" ? (
                          <div
                            style={{
                              width: 20,
                              height: 20,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                          >
                            <ThinkingOrb
                              state={isWebSearchAgent ? "searching" : "working"}
                              size={20}
                              style={{ background: "transparent" }}
                            />
                          </div>
                        ) : (
                          <svg
                            width="14"
                            height="14"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="3"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </span>
                    </div>
                    {agent.steps && agent.steps.length > 0 && (
                      <div className="moe-agent-steps">
                        {agent.steps.map((step: string, si: number) => (
                          <div
                            key={si}
                            className={`moe-step-line ${step.toLowerCase().includes("visited") || step.toLowerCase().includes("searching") ? "website-line" : ""}`}
                          >
                            {step}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="moe-collapsed-ongoing">
              <span className="pulse-dot" />
              <span className="moe-collapsed-text">
                {workingAgents.length > 0
                  ? `Active agents working: ${workingAgents.map((a: any) => a.label || `Agent ${a.agent_id}`).join(", ")}`
                  : "Agents processing request..."}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  } catch (e) {
    console.error("ThinkingOverlay error:", e);
    return null;
  }
}
