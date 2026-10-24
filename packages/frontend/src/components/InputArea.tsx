import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { ArrowUp, Loader2, Mic, Square } from "lucide-react";
import ModelSwitcher from "./ModelSwitcher";
import LoadingSpinner from "./LoadingSpinner";
import AgentAvatar from "./AgentAvatar";
import MicWave from "./MicWave";
import { useApp } from "../AppContext";
import type { ActivityMode } from "../AppContext";
import { useCommandHandlers } from "../commands/useCommand";
import { useChatStreamActions } from "../stream/context";
import { exportWAV } from "../utils/audio";
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
    activeSessionId,
    sessions,
    attachedFiles,
    setAttachedFiles,
    currentModel,
    activeView,
    selectedAgentId,
    isRecording,
    setIsRecording,
    isTranscribing,
    setIsTranscribing,
    addToast,
  } = useApp();

  const { send: sendMessage, stop: stopStream } = useChatStreamActions();

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
  // When set, the next handleSend() uses this text instead of the composer
  // value. Used by the "regenerate" command to replay a previous message.
  const sendOverrideRef = useRef<string | null>(null);

  const [moePopupOpen, setMoePopupOpen] = useState(false);
  const moeBtnRef = useRef<HTMLButtonElement>(null);
  const moePopupRef = useRef<HTMLDivElement>(null);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [popupPos, setPopupPos] = useState<{ top?: number; bottom?: number; left: number } | null>(null);
  const [allAgents, setAllAgents] = useState<AgentListItem[]>([]);
  const [mention, setMention] = useState<{ query: string } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const pcmRef = useRef<Float32Array[]>([]);
  const levelRef = useRef(0);

  useEffect(() => {
    api.agents
      .list()
      .then((d) => setAllAgents((d.agents || []).filter((a) => a.enabled)))
      .catch(() => {});
  }, []);

  // ── voice input (speech-to-text) ──────────────────────────────────
  // Captures raw PCM via Web Audio (portable across Chromium and WebKitGTK,
  // unlike MediaRecorder codecs), converts to WAV and posts to /voice/transcribe.
  const stopMediaTracks = () => {
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
  };

  const transcribePcm = async (samples: Float32Array, sampleRate: number) => {
    setIsTranscribing(true);
    try {
      const wav = exportWAV(samples, sampleRate);
      const res = await api.voice.transcribe(wav);
      const text = (res.text || "").trim();
      if (text) {
        setValue((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
        requestAnimationFrame(() => textareaRef.current?.focus());
      } else if (res.error) {
        addToast(res.error);
      }
    } catch (e) {
      addToast(`Transcription failed: ${e instanceof Error ? e.message : String(e)}`);
    }
    setIsTranscribing(false);
  };

  const startRecording = async () => {
    if (isRecording || isTranscribing) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      sourceNodeRef.current = source;
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      pcmRef.current = [];
      processor.onaudioprocess = (e) => {
        const chan = e.inputBuffer.getChannelData(0);
        pcmRef.current.push(new Float32Array(chan));
        let sum = 0;
        for (let i = 0; i < chan.length; i++) sum += chan[i] * chan[i];
        const rms = Math.sqrt(sum / chan.length);
        levelRef.current = Math.min(1, rms * 6);
      };
      // A muted gain node keeps the processor running without playing the mic.
      const silent = ctx.createGain();
      silent.gain.value = 0;
      source.connect(processor);
      processor.connect(silent);
      silent.connect(ctx.destination);
      setIsRecording(true);
    } catch (e) {
      stopMediaTracks();
      levelRef.current = 0;
      addToast(`Microphone unavailable: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const stopRecording = async () => {
    if (!isRecording) return;
    setIsRecording(false);
    levelRef.current = 0;
    const ctx = audioCtxRef.current;
    const sampleRate = ctx?.sampleRate || 44100;
    try {
      processorRef.current?.disconnect();
    } catch {
      // ignore
    }
    try {
      sourceNodeRef.current?.disconnect();
    } catch {
      // ignore
    }
    stopMediaTracks();
    const chunks = pcmRef.current;
    pcmRef.current = [];
    processorRef.current = null;
    sourceNodeRef.current = null;
    audioCtxRef.current = null;
    if (ctx) {
      try {
        await ctx.close();
      } catch {
        // ignore
      }
    }
    const total = chunks.reduce((n, c) => n + c.length, 0);
    if (total === 0) return;
    const merged = new Float32Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    await transcribePcm(merged, sampleRate);
  };

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
    async (mode: "default" | "moe" | "deep_research") => {
      setLlmSubMode(mode);
      try {
        await api.config.setMoe({ moe_sub_mode: mode }, scope);
      } catch (e) {
        console.error("Failed to save sub mode:", e);
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
    const override = sendOverrideRef.current;
    sendOverrideRef.current = null;
    const text = (override ?? value).trim();
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

    // ── activity-chain metadata (same shell for every mode) ───────────
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
    } else if (llmSubMode === "deep_research") {
      actMode = "deep_research";
      actTitle = "Deep Research";
    }

    // When an agent is invoked in this PaliSpace, surface the same animated
    // profile-picture loading the Agents view uses.
    const mentionAtStart = text.match(/^@([\w-]+)/);
    const mentionedAgent = mentionAtStart
      ? allAgents.find((a) => a.name === mentionAtStart[1])
      : undefined;
    const agentLoading = mentionedAgent
      ? {
          seed: mentionedAgent.color_seed || mentionedAgent.id + mentionedAgent.name,
          name: mentionedAgent.name,
        }
      : null;

    const mode = isChatView ? "llm" : chatMode;

    sendMessage({
      text,
      userText: text || "Sent attachments.",
      mode,
      scope,
      sessionId: activeSessionId,
      subMode: mode === "llm" ? llmSubMode : undefined,
      files: selectedFiles.size > 0 ? Array.from(selectedFiles) : undefined,
      activity: {
        mode: actMode,
        title: actTitle,
        subtitle: actMode === "agent" ? "agent" : undefined,
        seed:
          actMode === "agent" && agentInfo
            ? agentInfo.color_seed || agentInfo.id + agentInfo.name
            : undefined,
      },
      agentLoading,
    });
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
    allAgents,
    activeView,
    selectedAgentId,
    sendMessage,
  ]);

  const findLastMessage = useCallback(
    (role: "user" | "system") => {
      const sess =
        sessions.find((s) => s.id === activeSessionId) ??
        (sessions.length > 0 ? sessions[sessions.length - 1] : undefined);
      if (!sess?.messages) return undefined;
      for (let i = sess.messages.length - 1; i >= 0; i--) {
        if (sess.messages[i].role === role) return sess.messages[i];
      }
      return undefined;
    },
    [sessions, activeSessionId],
  );

  useCommandHandlers({
    "chat.stop": () => {
      if (!isGenerating) {
        addToast("Nothing is generating.");
        return;
      }
      stopStream();
    },
    "chat.copy-last": () => {
      const last = findLastMessage("system");
      if (!last?.content) {
        addToast("No response to copy yet.");
        return;
      }
      navigator.clipboard
        .writeText(last.content)
        .then(() => addToast("Copied response to clipboard"))
        .catch(() => addToast("Could not access the clipboard"));
    },
    "chat.regenerate": () => {
      if (isGenerating) {
        addToast("A response is already generating.");
        return;
      }
      const last = findLastMessage("user");
      if (!last?.content) {
        addToast("No message to regenerate.");
        return;
      }
      sendOverrideRef.current = last.content;
      void handleSend();
    },
    "chat.attach": () => {
      textareaRef.current?.focus();
      addToast("Drop files onto the composer to attach them.");
    },
  });

  // Allow ChatArea's message actions to regenerate / edit-and-resend a
  // specific message by replaying its text through the normal send path.
  const handleSendRef = useRef(handleSend);
  handleSendRef.current = handleSend;

  useEffect(() => {
    const handler = (e: Event) => {
      const content = (e as CustomEvent).detail?.content as string | undefined;
      if (typeof content !== 'string' || !content.trim()) return;
      sendOverrideRef.current = content;
      void handleSendRef.current();
    };
    window.addEventListener('palimind:regenerate-message', handler);
    return () => window.removeEventListener('palimind:regenerate-message', handler);
  }, []);

  // Research projects can pre-fill the composer to continue prior work.
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail?.text as string | undefined;
      if (typeof text !== 'string') return;
      setValue(text);
      requestAnimationFrame(() => textareaRef.current?.focus());
    };
    window.addEventListener('palimind:prefill-composer', handler);
    return () => window.removeEventListener('palimind:prefill-composer', handler);
  }, []);

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
  const isDeepResearchActive = chatMode === "llm" && llmSubMode === "deep_research";

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
                  {isMoeActive ? "Mixture of Experts" : isDeepResearchActive ? "Deep Research" : "Default"}
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

                  <div
                    className="moe-popup-option"
                    onClick={() => {
                      handleSubModeChange("deep_research");
                      setMoePopupOpen(false);
                    }}
                  >
                    <div className="moe-popup-option-info">
                      <span className="moe-popup-option-name">
                        Deep Research
                      </span>
                      <span className="moe-popup-option-desc">
                        Multi-agent research pipeline with synthesis
                      </span>
                    </div>
                    {llmSubMode === "deep_research" && (
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
            {isRecording && (
              <span className="mic-listening" role="status" aria-live="polite">
                <MicWave levelRef={levelRef} active={isRecording} />
                Listening…
              </span>
            )}
            <PromptInputAction
              tooltip={
                isTranscribing
                  ? "Transcribing…"
                  : isRecording
                    ? "Stop recording"
                    : "Voice input"
              }
            >
              <button
                type="button"
                className={`mic-btn${isRecording ? " active" : ""}${isTranscribing ? " processing" : ""}`}
                aria-label={isRecording ? "Stop recording" : "Voice input"}
                title={isRecording ? "Stop recording" : "Voice input"}
                disabled={isTranscribing}
                onClick={() => (isRecording ? stopRecording() : startRecording())}
              >
                {isTranscribing ? (
                  <Loader2 size={16} className="spin" aria-hidden="true" />
                ) : (
                  <Mic size={16} aria-hidden="true" />
                )}
              </button>
            </PromptInputAction>
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
                    stopStream();
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
    </div>
  );
}
