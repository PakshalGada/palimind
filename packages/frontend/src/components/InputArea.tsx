import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { ArrowUp, Square } from "lucide-react";
import ModelSwitcher from "./ModelSwitcher";
import LoadingSpinner from "./LoadingSpinner";
import AgentAvatar from "./AgentAvatar";
import ActivityChain from "./ActivityChain";
import { useApp } from "../AppContext";
import type { ActivityMode, AgentState } from "../AppContext";
import { formatMarkdown } from "../utils/markdown";
import { api } from "../api";
import type { AgentListItem, ModelItem } from "../types";
import {
  PromptInput,
  PromptInputAction,
  PromptInputActions,
  PromptInputTextarea,
} from "./prompt-kit/prompt-input";
import { Button } from "./ui/button";

export default function InputArea() {
  const {
    chatMode,
    setChatMode,
    llmSubMode,
    setLlmSubMode,
    orchestratorModel,
    setOrchestratorModel,
    workerModel,
    setWorkerModel,
    selectedFiles,
    isGenerating,
    setIsGenerating,
    activeSessionId,
    attachedFiles,
    setAttachedFiles,
    currentModel,
    refreshSessions,
    setThinkingText,
    setAgentStates,
    setAgentLoading,
    activeView,
    selectedAgentId,
    setActivity,
  } = useApp();

  const isChatView = activeView === 'chat' || activeView === 'agents';
  // The Agents view reuses this exact composer but targets the selected
  // agent's own scope (separate sessions + model), not global chat.
  const scope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : isChatView
        ? 'chat'
        : 'field';

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const [moePopupOpen, setMoePopupOpen] = useState(false);
  const moeBtnRef = useRef<HTMLButtonElement>(null);
  const moePopupRef = useRef<HTMLDivElement>(null);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [popupPos, setPopupPos] = useState<{ top?: number; bottom?: number; left: number } | null>(null);
  const [allAgents, setAllAgents] = useState<AgentListItem[]>([]);
  const [mention, setMention] = useState<{ query: string } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [chainSlot, setChainSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    api.agents
      .list()
      .then((d) => setAllAgents((d.agents || []).filter((a) => a.enabled)))
      .catch(() => {});
  }, []);

  const mentionMatches = mention
    ? allAgents.filter((a) =>
        a.name.toLowerCase().includes(mention.query.toLowerCase()),
      )
    : [];

  const applyMention = useCallback(
    (agentName: string) => {
      setValue((prev) =>
        prev.replace(/(^|\s)@([\w-]*)$/, (_m, pre: string) => `${pre}@${agentName} `),
      );
      setMention(null);
      requestAnimationFrame(() => textareaRef.current?.focus());
    },
    [],
  );

  const updateMention = useCallback((text: string) => {
    const m = text.match(/(^|\s)@([\w-]*)$/);
    if (m) {
      setMention({ query: m[2] });
      setMentionIndex(0);
    } else {
      setMention(null);
    }
  }, []);
  const isEmpty = !value.trim() && attachedFiles.length === 0;

  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value]);

  const updatePopupPos = useCallback(() => {
    if (!moeBtnRef.current) return;
    const rect = moeBtnRef.current.getBoundingClientRect();
    const popupWidth = 340;
    const popupHeight = 400;

    let left = rect.right - popupWidth;
    if (left < 16) left = 16;
    if (left + popupWidth > window.innerWidth - 16) {
      left = window.innerWidth - popupWidth - 16;
    }

    const spaceAbove = rect.top;
    if (spaceAbove >= popupHeight || spaceAbove > window.innerHeight - rect.bottom) {
      setPopupPos({
        bottom: window.innerHeight - rect.top + 8,
        left,
      });
    } else {
      setPopupPos({
        top: rect.bottom + 8,
        left,
      });
    }
  }, []);

  useEffect(() => {
    if (!moePopupOpen) return;
    updatePopupPos();
    window.addEventListener("resize", updatePopupPos);
    window.addEventListener("scroll", updatePopupPos, true);
    return () => {
      window.removeEventListener("resize", updatePopupPos);
      window.removeEventListener("scroll", updatePopupPos, true);
    };
  }, [moePopupOpen, updatePopupPos, llmSubMode]);

  useEffect(() => {
    if (!moePopupOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        moePopupRef.current &&
        !moePopupRef.current.contains(e.target as Node) &&
        moeBtnRef.current &&
        !moeBtnRef.current.contains(e.target as Node)
      ) {
        setMoePopupOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [moePopupOpen]);

  const fetchModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      const data = await api.models.list();
      if (data.models) setModels(data.models);
    } catch {
      // silently fail
    }
    setModelsLoading(false);
  }, []);

  useEffect(() => {
    if (moePopupOpen && models.length === 0) {
      fetchModels();
    }
  }, [moePopupOpen, models.length, fetchModels]);

  const handleSubModeChange = useCallback(
    async (mode: "default" | "moe") => {
      setLlmSubMode(mode);
      try {
        await api.config.setMoe({ moe_sub_mode: mode }, scope);
      } catch (e) {
        console.error("Failed to save MoE sub mode:", e);
      }
    },
    [setLlmSubMode, scope],
  );

  const parseParamsB = (model: ModelItem): number => {
    if (model.parameter_size) {
      const m = model.parameter_size.match(/^(\d+(?:\.\d+)?)/);
      if (m) return parseFloat(m[1]);
    }
    const mId = model.model_id.toLowerCase();
    const parts = mId.split(":");
    if (parts.length > 1) {
      const sizeM = parts[1].match(/^(\d+(?:\.\d+)?)/);
      if (sizeM) return parseFloat(sizeM[1]);
    }
    const nameM = mId.match(/(\d+)b/);
    if (nameM) return parseFloat(nameM[1]);
    return 7;
  };

  const sortedModels = [...models].sort(
    (a, b) => parseParamsB(b) - parseParamsB(a),
  );

  // Online (OpenCode proxy) models have no local size metadata.
  const isOnline = (m: ModelItem) => !m.parameter_size && !m.size_gb;

  const handleSend = useCallback(async () => {
    if (isGenerating) return;
    const text = value.trim();
    if (!text && attachedFiles.length === 0) return;

    // Index dropped attachments as captures so document-mode RAG can find them.
    if (attachedFiles.length > 0) {
      try {
        await Promise.all(
          attachedFiles.map(async (file) => {
            const content = await file.text();
            await fetch("/api/capture/file", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name: file.name, content }),
            });
          }),
        );
      } catch (e) {
        console.error("attachment upload failed:", e);
      }
    }

    setValue("");
    setAttachedFiles([]);
    setIsGenerating(true);

    const abortCtrl = new AbortController();
    abortRef.current = abortCtrl;
    (
      window as unknown as { __abortController: AbortController }
    ).__abortController = abortCtrl;

    const messagesContainer = document.getElementById(
      "streaming-messages-container",
    );
    const chatInterface = document.getElementById("chat-interface");
    if (chatInterface) chatInterface.classList.remove("empty-chat");

    if (messagesContainer) messagesContainer.innerHTML = "";

    const userMsgDiv = document.createElement("div");
    userMsgDiv.className = "message user-message";
    userMsgDiv.innerHTML = `<div class="message-wrapper"><div class="message-content" style="background:var(--msg-user-bg);border:1px solid var(--border-color);padding:12px 16px;border-radius:var(--radius-lg);max-width:100%;font-size:0.9rem;">${text || "Sent attachments."}</div></div>`;
    messagesContainer?.appendChild(userMsgDiv);
    // Chain-of-thought slot: directly below the question, in the answer stream.
    const chainSlotEl = document.createElement("div");
    chainSlotEl.className = "cot-inline";
    userMsgDiv.insertAdjacentElement("afterend", chainSlotEl);
    setChainSlot(chainSlotEl);
    const scrollArea = document.getElementById("messages-scroll-area");
    if (scrollArea) {
      scrollArea.scrollTo({
        top: userMsgDiv.offsetTop - 16,
        behavior: "smooth",
      });
    }

    setThinkingText("Thinking...");
    setAgentStates([]);
    setAgentLoading(null);
    const thinkingBaseRef = { current: "Thinking..." };

    // ── unified activity chain (same shell for every mode) ────────────
    const agentInfo = selectedAgentId
      ? allAgents.find((a) => a.id === selectedAgentId)
      : undefined;
    let actMode: ActivityMode = "llm";
    let actTitle = "LLM";
    if (activeView === "agents") {
      actMode = "agent";
      actTitle = agentInfo?.name || "Agent";
    } else if (chatMode === "document") {
      actMode = "document";
      actTitle = "Document";
    } else if (llmSubMode === "moe") {
      actMode = "moe";
      actTitle = "Mixture of Experts";
    }
    setActivity({
      mode: actMode,
      title: actTitle,
      subtitle: actMode === "agent" ? "agent" : undefined,
      seed:
        actMode === "agent" && agentInfo
          ? agentInfo.color_seed || agentInfo.id + agentInfo.name
          : undefined,
      steps: [],
    });

    let stepSeq = 0;
    const newId = () => `st${Date.now().toString(36)}${(stepSeq++).toString(36)}`;
    const addStep = (kind: string, title: string, detail = "") => {
      thinkingBaseRef.current = title;
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: [
                ...prev.steps,
                { id: newId(), kind, title, detail, status: "active" as const },
              ],
            }
          : prev,
      );
    };
    const completeActive = () =>
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: prev.steps.map((s) =>
                s.status === "active" ? { ...s, status: "done" as const } : s,
              ),
            }
          : prev,
      );
    const setActiveDetail = (text: string) =>
      setActivity((prev) => {
        if (!prev || prev.steps.length === 0) return prev;
        const steps = [...prev.steps];
        const i = steps.length - 1;
        steps[i] = { ...steps[i], detail: text.length > 2000 ? text.slice(-2000) : text };
        return { ...prev, steps };
      });
    const agentStepIds: Record<number, string> = {};
    const addAgentStep = (aid: number, title: string, detail = "") => {
      thinkingBaseRef.current = title;
      const sid = newId();
      agentStepIds[aid] = sid;
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: [
                ...prev.steps,
                {
                  id: sid,
                  kind: "agent",
                  title,
                  detail,
                  status: "active" as const,
                  children: [],
                },
              ],
            }
          : prev,
      );
    };
    const completeAgentStep = (aid: number) => {
      const sid = agentStepIds[aid];
      if (!sid) return;
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: prev.steps.map((s) =>
                s.id === sid ? { ...s, status: "done" as const } : s,
              ),
            }
          : prev,
      );
    };
    const appendAgentChild = (aid: number, text: string) => {
      const sid = agentStepIds[aid];
      if (!sid) return;
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: prev.steps.map((s) =>
                s.id === sid
                  ? {
                      ...s,
                      children: [
                        ...(s.children || []),
                        { id: newId(), kind: "thought", title: text, status: "done" as const },
                      ],
                    }
                  : s,
              ),
            }
          : prev,
      );
    };
    const reasonKind = (text: string): string => {
      const t = text.toLowerCase();
      if (t.includes("document mode") || t.includes("llm mode")) return "mode";
      if (t.includes("routing")) return "route";
      if (t.includes("briefing")) return "briefing";
      if (t.includes("planning") || t.includes("plan")) return "plan";
      if (t.includes("graph")) return "graph";
      if (t.includes("search")) return "search";
      if (t.includes("passage") || t.includes("source")) return "docs";
      if (t.includes("synthesi")) return "synthesis";
      if (t.includes("verif")) return "verify";
      if (t.includes("generat")) return "answer";
      return "info";
    };
    let agentsStarted = false;
    let reasoningStarted = false;
    let answerStarted = false;

    // When an agent is being invoked in this PaliSpace, surface the same
    // animated profile-picture loading the Agents view uses.
    const mentionAtStart = text.match(/^@([\w-]+)/);
    if (mentionAtStart) {
      const agent = allAgents.find((a) => a.name === mentionAtStart[1]);
      if (agent) {
        setAgentLoading({
          seed: agent.color_seed || agent.id + agent.name,
          name: agent.name,
        });
      }
    }

    const startTime = Date.now();
    let totalThoughtDuration = "";
    const timerInterval = setInterval(() => {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      setThinkingText(`${thinkingBaseRef.current} ${elapsed}s`);
    }, 200);

    const mode = isChatView ? "llm" : chatMode;
    const sub_mode = mode === "llm" ? llmSubMode : "";
    const url =
      `/api/chat?q=${encodeURIComponent(text)}&chat_mode=${mode}&scope=${scope}${sub_mode ? `&llm_sub_mode=${sub_mode}` : ""}${activeSessionId ? `&session_id=${activeSessionId}` : ""}` +
      (selectedFiles.size > 0
        ? `&files=${encodeURIComponent(Array.from(selectedFiles).join(","))}`
        : "");

    const eventSource = new EventSource(url);

    abortCtrl.signal.addEventListener("abort", () => {
      eventSource.close();
      clearInterval(timerInterval);
      setThinkingText("");
      setAgentStates([]);
      setAgentLoading(null);
      setActivity(null);
      setChainSlot(null);
      setIsGenerating(false);
      refreshSessions().then(() => {
        if (messagesContainer) messagesContainer.innerHTML = "";
      });
    });

    let contentDiv: HTMLElement | null = null;
    let fullText = "";
    let thinkingDetails: HTMLDetailsElement | null = null;
    let thinkingBody: HTMLElement | null = null;

    const fmtTs = (s: number) => {
      const sec = Math.round(s);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const r = sec % 60;
      return h > 0
        ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`
        : `${m}:${String(r).padStart(2, "0")}`;
    };

    const openVideoPlayer = (
      filePath: string,
      start: number,
      end?: number | null,
    ) => {
      const existing = document.getElementById("palimind-video-overlay");
      if (existing) existing.remove();
      const overlay = document.createElement("div");
      overlay.id = "palimind-video-overlay";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;display:flex;align-items:center;justify-content:center;";
      const panel = document.createElement("div");
      panel.style.cssText =
        "background:var(--bg-color,#111);border:1px solid var(--border-color,#333);border-radius:12px;padding:12px;max-width:min(880px,90vw);width:100%;";
      const video = document.createElement("video");
      video.style.cssText = "width:100%;max-height:65vh;border-radius:8px;background:#000;";
      video.controls = true;
      video.src = `/api/media/stream?path=${encodeURIComponent(filePath)}`;
      const label = document.createElement("div");
      label.style.cssText =
        "color:var(--text-main,#eee);font-size:0.85rem;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;";
      const titleSpan = document.createElement("span");
      titleSpan.textContent = `${filePath} @ ${fmtTs(start)}${end ? `–${fmtTs(end)}` : ""}`;
      const closeBtn = document.createElement("button");
      closeBtn.textContent = "Close";
      closeBtn.style.cssText =
        "background:none;border:none;color:inherit;font-size:1rem;cursor:pointer;padding:4px 8px;";
      closeBtn.onclick = () => {
        video.pause();
        overlay.remove();
      };
      label.appendChild(titleSpan);
      label.appendChild(closeBtn);
      panel.appendChild(label);
      panel.appendChild(video);
      overlay.appendChild(panel);
      overlay.onclick = (e) => {
        if (e.target === overlay) {
          video.pause();
          overlay.remove();
        }
      };
      document.body.appendChild(overlay);
      video.onloadedmetadata = () => {
        video.currentTime = start;
        void video.play().catch(() => {});
      };
    };

    const renderMediaCitations = (
      citations: {
        file: string;
        start: number;
        end?: number | null;
        snippet?: string;
      }[],
    ) => {
      if (!citations.length || !messagesContainer) return;
      const row = document.createElement("div");
      row.className = "media-citations-row";
      row.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin:10px 0;";
      citations.forEach((c) => {
        const chip = document.createElement("button");
        chip.className = "media-citation-chip";
        chip.title = c.snippet || c.file;
        chip.style.cssText =
          "display:inline-flex;align-items:center;gap:6px;background:var(--accent-bg);color:var(--text-main);border:1px solid var(--border-color,#444);border-radius:999px;padding:4px 12px;font-size:0.78rem;cursor:pointer;";
        const baseName = c.file.split(/[\\/]/).pop() || c.file;
        chip.textContent = `▶ ${baseName} @ ${fmtTs(c.start)}`;
        chip.onclick = () => openVideoPlayer(c.file, c.start, c.end);
        row.appendChild(chip);
      });
      messagesContainer.appendChild(row);
    };

    const renderTextCitations = (
      citations: {
        file: string;
        section?: string;
        snippet?: string;
        chunk_id?: number;
      }[],
    ) => {
      if (!citations.length || !messagesContainer) return;
      const row = document.createElement("div");
      row.className = "media-citations-row";
      row.style.cssText = "display:flex;flex-wrap:wrap;gap:6px;margin:10px 0;";
      citations.forEach((c) => {
        const chip = document.createElement("span");
        chip.className = "media-citation-chip";
        chip.title = c.snippet || c.file;
        chip.style.cssText =
          "display:inline-flex;align-items:center;gap:6px;background:var(--accent-bg);color:var(--text-main);border:1px solid var(--border-color,#444);border-radius:999px;padding:4px 12px;font-size:0.78rem;";
        const baseName = c.file.split(/[\\/]/).pop() || c.file;
        chip.textContent = c.section ? `${baseName} → ${c.section}` : baseName;
        row.appendChild(chip);
      });
      messagesContainer.appendChild(row);
    };

    eventSource.onmessage = async (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "sources") {
        if (data.sources?.length) {
          fullText = `*Sources: ${data.sources.join(", ")}*\n\n`;
          contentDiv = document.createElement("div");
          contentDiv.className = "message-content";
          contentDiv.innerHTML = formatMarkdown(fullText);
          const wrapper = document.createElement("div");
          wrapper.className = "message-wrapper";
          wrapper.appendChild(contentDiv);
          const msgDiv = document.createElement("div");
          msgDiv.className = "message system-message";
          msgDiv.appendChild(wrapper);
          messagesContainer?.appendChild(msgDiv);
        }
      } else if (data.type === "media_citations") {
        renderMediaCitations(data.citations || []);
      } else if (data.type === "citations") {
        renderTextCitations(data.citations || []);
      } else if (data.type === "reasoning") {
        const reasonText = String(data.text || "").replace(/[>*_]/g, "").trim();
        setThinkingText(reasonText);
        completeActive();
        addStep(reasonKind(reasonText), reasonText);
      } else if (data.type === "thinking") {
        const t = String(data.text || "").trim();
        if (!t || !messagesContainer) return;
        if (!thinkingDetails) {
          thinkingDetails = document.createElement("details");
          thinkingDetails.className = "thinking-block";
          const summary = document.createElement("summary");
          summary.className = "thinking-toggle";
          summary.textContent = "Thinking";
          thinkingDetails.appendChild(summary);
          thinkingBody = document.createElement("div");
          thinkingBody.className = "thinking-body";
          thinkingDetails.appendChild(thinkingBody);
          const wrapper = document.createElement("div");
          wrapper.className = "message-wrapper";
          wrapper.appendChild(thinkingDetails);
          const msgDiv = document.createElement("div");
          msgDiv.className = "message system-message";
          msgDiv.appendChild(wrapper);
          messagesContainer.appendChild(msgDiv);
        }
        thinkingBody!.textContent = (thinkingBody!.textContent || "") + t;
        if (!reasoningStarted) {
          completeActive();
          addStep("reason", "Reasoning");
          reasoningStarted = true;
        }
        setActiveDetail(t);
      } else if (data.type === "progress") {
        setThinkingText(data.text);
      } else if (data.type === "agent_progress") {
        setAgentStates((prev: AgentState[]) => {
          const aid = data.agent_id as number;
          const existing = prev.find((a) => a.agent_id === aid);
          if (existing) {
            return prev.map((a) =>
              a.agent_id === aid
                ? {
                    ...a,
                    status: data.status || a.status,
                    task: data.task || a.task,
                  }
                : a,
            );
          }
          const newAgent: AgentState = {
            agent_id: aid,
            label: data.label || `Agent ${aid}`,
            task: data.task || "",
            status: (data.status as "working" | "complete") || "working",
            steps: [],
          };
          return [...prev, newAgent];
        });
        const aid = data.agent_id as number;
        if ((data.status || "working") === "complete") {
          completeAgentStep(aid);
        } else if (!agentStepIds[aid]) {
          if (!agentsStarted) {
            completeActive();
            agentsStarted = true;
          }
          addAgentStep(aid, data.label || `Agent ${aid}`, data.task || "");
        }
      } else if (data.type === "agent_thinking") {
        const aid = data.agent_id as number;
        const step = data.text as string;
        setAgentStates((prev: AgentState[]) => {
          return prev.map((a) =>
            a.agent_id === aid ? { ...a, steps: [...a.steps, step] } : a,
          );
        });
        appendAgentChild(aid, step);
      } else if (data.type === "agent:thought") {
        const t = String(data.text || "").replace(/\s+/g, " ").trim();
        if (t && !t.startsWith("FINAL_ANSWER")) {
          setThinkingText(t.slice(0, 90));
          completeActive();
          addStep("thought", "Thinking", t.slice(0, 400));
        }
      } else if (data.type === "agent:tool_call") {
        setThinkingText(`Using tool: ${String(data.tool || "…")}`);
        completeActive();
        addStep(
          "tool",
          String(data.tool || "tool"),
          data.args != null ? JSON.stringify(data.args) : "",
        );
      } else if (data.type === "agent:completed") {
        if (!answerStarted) {
          completeActive();
          addStep("answer", "Answer");
          answerStarted = true;
        }
        clearInterval(timerInterval);
        setThinkingText("");
        const finalOutput = String(data.output || "").trim();
        if (finalOutput) {
          fullText = finalOutput;
          if (!contentDiv) {
            if (!totalThoughtDuration) {
              const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
              totalThoughtDuration = `${elapsed}s`;
            }
            contentDiv = document.createElement("div");
            contentDiv.className = "message-content";
            const wrapper = document.createElement("div");
            wrapper.className = "message-wrapper";
            const badgeDiv = document.createElement("div");
            badgeDiv.className = "thought-duration-badge";
            badgeDiv.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Thought for ${totalThoughtDuration}`;
            wrapper.appendChild(badgeDiv);
            wrapper.appendChild(contentDiv);
            const msgDiv = document.createElement("div");
            msgDiv.className = "message system-message";
            msgDiv.appendChild(wrapper);
            messagesContainer?.appendChild(msgDiv);
          }
          contentDiv.innerHTML = formatMarkdown(fullText);
        }
      } else if (data.type === "agent:waiting_for_human") {
        setThinkingText(`Awaiting approval: ${data.tool || "action"}`);
        completeActive();
        addStep("approval", "Approval required", String(data.tool || ""));
        if (!messagesContainer) return;
        const card = document.createElement("div");
        card.className = "approval-card";
        card.style.cssText =
          "border:1px solid var(--border-color);border-radius:10px;padding:12px;margin:8px 0;max-width:640px;background:var(--panel-bg);";
        const title = document.createElement("div");
        title.style.cssText = "font-size:0.85rem;color:var(--text-main);margin-bottom:8px;";
        title.innerHTML = `<strong>Approval required</strong> — <code>${String(data.tool || "")}</code>`;
        card.appendChild(title);
        if (data.args != null) {
          const pre = document.createElement("pre");
          pre.style.cssText =
            "margin:0 0 8px;padding:8px;background:var(--bg-color);border-radius:6px;font-size:0.75rem;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word;max-height:180px;overflow:auto;";
          pre.textContent =
            typeof data.args === "string" ? data.args : JSON.stringify(data.args, null, 2);
          card.appendChild(pre);
        }
        const correction = document.createElement("input");
        correction.type = "text";
        correction.placeholder = "Optional correction / feedback…";
        correction.style.cssText =
          "width:100%;padding:7px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--input-bg);color:var(--text-main);margin-bottom:8px;";
        card.appendChild(correction);
        const row = document.createElement("div");
        row.style.cssText = "display:flex;gap:8px;";
        const approveBtn = document.createElement("button");
        approveBtn.textContent = "Approve";
        approveBtn.className = "action-btn primary";
        const rejectBtn = document.createElement("button");
        rejectBtn.textContent = "Reject";
        rejectBtn.className = "action-btn danger-btn";
        const finish = (approved: boolean) => {
          approveBtn.disabled = true;
          rejectBtn.disabled = true;
          correction.disabled = true;
          const status = document.createElement("div");
          status.style.cssText = "font-size:0.78rem;color:var(--text-muted);margin-top:6px;";
          status.textContent = approved ? "Approved — resuming…" : "Rejected.";
          card.appendChild(status);
          api.agents
            .approve(String(data.agent_id), approved, correction.value)
            .catch(() => {});
          setThinkingText(approved ? "Resuming…" : "Rejected");
        };
        approveBtn.onclick = () => finish(true);
        rejectBtn.onclick = () => finish(false);
        row.appendChild(approveBtn);
        row.appendChild(rejectBtn);
        card.appendChild(row);
        messagesContainer.appendChild(card);
        const approvalScroll = document.getElementById("messages-scroll-area");
        if (approvalScroll) approvalScroll.scrollTop = approvalScroll.scrollHeight;
      } else if (data.type === "agent:token") {
        if (!answerStarted) {
          completeActive();
          addStep("answer", "Answer");
          answerStarted = true;
        }
        if (data.reset) {
          fullText = "";
          if (contentDiv) contentDiv.innerHTML = "";
        } else if (data.text) {
          if (!contentDiv) {
            clearInterval(timerInterval);
            setThinkingText("");
            if (!totalThoughtDuration) {
              const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
              totalThoughtDuration = `${elapsed}s`;
            }
            contentDiv = document.createElement("div");
            contentDiv.className = "message-content";
            const wrapper = document.createElement("div");
            wrapper.className = "message-wrapper";
            const badgeDiv = document.createElement("div");
            badgeDiv.className = "thought-duration-badge";
            badgeDiv.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Thought for ${totalThoughtDuration}`;
            wrapper.appendChild(badgeDiv);
            wrapper.appendChild(contentDiv);
            const msgDiv = document.createElement("div");
            msgDiv.className = "message system-message";
            msgDiv.appendChild(wrapper);
            messagesContainer?.appendChild(msgDiv);
          }
          fullText += data.text;
          contentDiv.innerHTML = formatMarkdown(fullText);
        }
      } else if (data.type === "token") {
        if (!answerStarted) {
          completeActive();
          addStep("answer", "Answer");
          answerStarted = true;
        }
        if (!contentDiv) {
          clearInterval(timerInterval);
          setThinkingText("");
          if (!totalThoughtDuration) {
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
            totalThoughtDuration = `${elapsed}s`;
          }
          contentDiv = document.createElement("div");
          contentDiv.className = "message-content";
          const wrapper = document.createElement("div");
          wrapper.className = "message-wrapper";

          const badgeDiv = document.createElement("div");
          badgeDiv.className = "thought-duration-badge";
          badgeDiv.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Thought for ${totalThoughtDuration}`;
          wrapper.appendChild(badgeDiv);
          wrapper.appendChild(contentDiv);

          const msgDiv = document.createElement("div");
          msgDiv.className = "message system-message";
          msgDiv.appendChild(wrapper);
          messagesContainer?.appendChild(msgDiv);
        }
        fullText += data.text;
        contentDiv.innerHTML = formatMarkdown(fullText);
      } else if (data.type === "error") {
        clearInterval(timerInterval);
        setThinkingText("");
        setAgentStates([]);
        setAgentLoading(null);
        setActivity(null);
        setChainSlot(null);
        if (!contentDiv) {
          contentDiv = document.createElement("div");
          contentDiv.className = "message-content";
          const wrapper = document.createElement("div");
          wrapper.className = "message-wrapper";
          wrapper.appendChild(contentDiv);
          const msgDiv = document.createElement("div");
          msgDiv.className = "message system-message";
          msgDiv.appendChild(wrapper);
          messagesContainer?.appendChild(msgDiv);
        }
        fullText += `\n**Error:** ${data.text}`;
        contentDiv.innerHTML = formatMarkdown(fullText);
        eventSource.close();
        setIsGenerating(false);
        refreshSessions().then(() => {
          if (messagesContainer) messagesContainer.innerHTML = "";
        });
      } else if (data.type === "done") {
        clearInterval(timerInterval);
        setThinkingText("");
        setAgentStates([]);
        setAgentLoading(null);
        setActivity(null);
        setChainSlot(null);
        eventSource.close();
        setIsGenerating(false);
        refreshSessions().then(() => {
          if (messagesContainer) messagesContainer.innerHTML = "";
        });
      }
    };

    eventSource.onerror = () => {
      clearInterval(timerInterval);
      setThinkingText("");
      setAgentStates([]);
      setAgentLoading(null);
      setActivity(null);
      setChainSlot(null);
      eventSource.close();
      setIsGenerating(false);
      refreshSessions().then(() => {
        if (messagesContainer) messagesContainer.innerHTML = "";
      });
    };
  }, [
    value,
    isGenerating,
    chatMode,
    isChatView,
    scope,
    llmSubMode,
    activeSessionId,
    selectedFiles,
    attachedFiles,
    setAttachedFiles,
    setIsGenerating,
    refreshSessions,
    allAgents,
    activeView,
    selectedAgentId,
    setActivity,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (mention && mentionMatches.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((i) => (i + 1) % mentionMatches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        applyMention(mentionMatches[mentionIndex].name);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(null);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const removeAttachment = (index: number) => {
    setAttachedFiles(attachedFiles.filter((_, i) => i !== index));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.currentTarget.classList.add("drag-over");
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.currentTarget.classList.remove("drag-over");
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.currentTarget.classList.remove("drag-over");
    if (e.dataTransfer.files.length) {
      setAttachedFiles([...attachedFiles, ...Array.from(e.dataTransfer.files)]);
    }
  };

  const isMoeActive = chatMode === "llm" && llmSubMode === "moe";

  return (
    <div className="input-area">
      {!isChatView && (
      <div
        className="chat-mode-toggle"
        title="Document: answers only from your indexed files. LLM: chat directly with the model."
      >
        <label className="toggle-switch">
          <input
            type="checkbox"
            checked={chatMode === "llm"}
            onChange={(e) => setChatMode(e.target.checked ? "llm" : "document")}
          />
          <div className="toggle-slider">
            <span className="toggle-label document-mode">Document</span>
            <span className="toggle-label llm-mode">LLM</span>
          </div>
        </label>
      </div>
      )}



      <PromptInput
        className="ai-command-center"
        id="ai-command-center"
        value={value}
        onValueChange={(nextValue) => {
          setValue(nextValue);
          updateMention(nextValue);
        }}
        isLoading={isGenerating}
        onSubmit={handleSend}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {attachedFiles.length > 0 && (
          <div className="attachment-chips">
            {attachedFiles.map((file, idx) => (
              <div key={idx} className="attachment-chip">
                <span className="chip-icon">
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                    <polyline points="13 2 13 9 20 9" />
                  </svg>
                </span>
                <span className="chip-name" title={file.name}>
                  {file.name}
                </span>
                <span className="chip-size">
                  {(file.size / 1024).toFixed(1)}KB
                </span>
                <button
                  type="button"
                  className="chip-remove"
                  onClick={() => removeAttachment(idx)}
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {mention && (
          <div className="agent-mention-popup">
            <div className="agent-mention-header">Call an agent</div>
            {mentionMatches.length === 0 && (
              <div className="agent-mention-empty">No matching agents</div>
            )}
            {mentionMatches.map((a, i) => (
              <div
                key={a.id}
                className={`agent-mention-item${i === mentionIndex ? " selected" : ""}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  applyMention(a.name);
                }}
                onMouseEnter={() => setMentionIndex(i)}
              >
                <AgentAvatar seed={a.color_seed || a.id + a.name} thinking={!!a.running} size={20} />
                <span className="agent-mention-name">@{a.name}</span>
              </div>
            ))}
          </div>
        )}

        <PromptInputTextarea
          id="chat-input"
          ref={textareaRef}
          rows={1}
          aria-label="Chat message"
          placeholder="Ask me anything..."
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            updateMention(e.target.value);
          }}
          onKeyDown={handleKeyDown}
        />

        <div className="composer-footer">
          {chatMode === "llm" && (
            <div className="moe-toggle-wrapper">
              <button
                ref={moeBtnRef}
                type="button"
                className={`moe-toggle-btn${isMoeActive ? " moe-active" : ""}`}
                onClick={() => setMoePopupOpen(!moePopupOpen)}
              >
                <span className="moe-btn-label">
                  {isMoeActive ? "Mixture of Experts" : "Default"}
                </span>
                <svg
                  className="moe-btn-chevron"
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              {moePopupOpen && popupPos && createPortal(
                <div
                  className="moe-popup"
                  ref={moePopupRef}
                  style={{
                    position: "fixed",
                    top: popupPos.top !== undefined ? `${popupPos.top}px` : "auto",
                    bottom: popupPos.bottom !== undefined ? `${popupPos.bottom}px` : "auto",
                    left: `${popupPos.left}px`,
                    zIndex: 999999,
                  }}
                >
                  <div
                    className="moe-popup-option"
                    onClick={() => {
                      handleSubModeChange("default");
                      setMoePopupOpen(false);
                    }}
                  >
                    <div className="moe-popup-option-info">
                      <span className="moe-popup-option-name">Default</span>
                      <span className="moe-popup-option-desc">
                        Standard LLM chat — single model
                      </span>
                    </div>
                    {llmSubMode === "default" && (
                      <svg
                        className="moe-popup-check"
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </div>
                  <div
                    className="moe-popup-option"
                    onClick={() => {
                      handleSubModeChange("moe");
                    }}
                  >
                    <div className="moe-popup-option-info">
                      <span className="moe-popup-option-name">
                        Mixture of Experts
                      </span>
                      <span className="moe-popup-option-desc">
                        4 parallel agents with tool access
                      </span>
                    </div>
                    {llmSubMode === "moe" && (
                      <svg
                        className="moe-popup-check"
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </div>

                  {llmSubMode === "moe" && (
                    <div className="moe-popup-models">
                      <div className="moe-popup-field">
                        <label className="moe-popup-label">Orchestrator</label>
                        <div className="moe-popup-hint">Plans and synthesizes results</div>
                        <div className="moe-popup-model-list">
                          {modelsLoading ? (
                            <LoadingSpinner size="sm" text="Loading models..." className="moe-popup-loading" />
                          ) : (
                            sortedModels.map((m) => (
                              <div
                                key={m.model_id}
                                className={`moe-popup-model-item${(orchestratorModel || currentModel) === m.model_id ? " selected" : ""}`}
                                onClick={() => {
                                  setOrchestratorModel(m.model_id);
                                  api.config
                                    .setMoe({ moe_orchestrator_model: m.model_id }, scope)
                                    .catch(() => {});
                                }}
                              >
                                <span className="moe-popup-model-name">
                                  {m.display_name || m.model_id}
                                </span>
                                <span className="moe-popup-model-size">
                                  {isOnline(m) ? "online" : m.size_gb ? `${m.size_gb}GB` : m.parameter_size || ""}
                                </span>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                      <div className="moe-popup-field">
                        <label className="moe-popup-label">Worker</label>
                        <div className="moe-popup-hint">Runs the expert agents in parallel</div>
                        <div className="moe-popup-model-list">
                          {modelsLoading ? (
                            <LoadingSpinner size="sm" text="Loading models..." className="moe-popup-loading" />
                          ) : (
                            sortedModels.map((m) => (
                              <div
                                key={m.model_id}
                                className={`moe-popup-model-item${(workerModel || currentModel) === m.model_id ? " selected" : ""}`}
                                onClick={() => {
                                  setWorkerModel(m.model_id);
                                  api.config
                                    .setMoe({ moe_worker_model: m.model_id }, scope)
                                    .catch(() => {});
                                }}
                              >
                                <span className="moe-popup-model-name">
                                  {m.display_name || m.model_id}
                                </span>
                                <span className="moe-popup-model-size">
                                  {isOnline(m) ? "online" : m.size_gb ? `${m.size_gb}GB` : m.parameter_size || ""}
                                </span>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>,
                document.body
              )}
            </div>
          )}

          <PromptInputActions className="prompt-composer-actions">
            <PromptInputAction
              tooltip={isGenerating ? "Stop generation" : "Send message"}
            >
              <Button
                id="btn-send"
                type="button"
                variant="default"
                size="icon"
                className={`send-btn${isGenerating ? " animating-stop" : ""}`}
                disabled={!isGenerating && isEmpty}
                onClick={() => {
                  if (isGenerating) {
                    const ac = (
                      window as unknown as { __abortController?: AbortController }
                    ).__abortController;
                    if (ac) ac.abort();
                    setIsGenerating(false);
                  } else {
                    handleSend();
                  }
                }}
              >
                {isGenerating ? (
                  <Square className="stop-icon" aria-hidden="true" />
                ) : (
                  <ArrowUp className="send-icon" aria-hidden="true" />
                )}
              </Button>
            </PromptInputAction>
          </PromptInputActions>
        </div>
      </PromptInput>
      <ModelSwitcher />
      {chainSlot && createPortal(<ActivityChain />, chainSlot)}
    </div>
  );
}
