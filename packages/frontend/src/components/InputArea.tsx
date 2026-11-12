import { memo, useState, useRef, useEffect, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { ArrowUp, Code2, FileText, Globe2, Loader2, Mic, Presentation, Search, Sparkles, Square, Users } from "lucide-react";
import ModelSwitcher from "./ModelSwitcher";
import ModelPicker from "../features/agents/ModelPicker";
import OfficeExportWatcher, { type OfficeJob } from "./OfficeExportWatcher";
import {
  applyMention as applyAgentMention,
  findMentionToken,
  firstAgentMention,
  type MentionToken,
} from "../utils/mentions";
import {
  SLASH_COMMANDS,
  commandBadge,
  filterSlashCommands,
  findSlashToken,
  insertSlashCommand,
  leadingCommand,
  parseArtifactCommand,
  removeLeadingCommand,
  stripSlashToken,
  type SlashCommand,
  type SlashToken,
} from "../utils/slashCommands";
import {
  CREATE_ARTIFACT_OPTIONS,
  buildArtifactPrompt,
} from "../utils/artifactPrompts";
import { PixelBurst } from "./pixel/PixelBurst";
import { useOneShot } from "./pixel/useOneShot";
import LoadingSpinner from "./LoadingSpinner";
import AgentAvatar from "./AgentAvatar";
import { ComposerCaption } from "./ComposerCaption";
import { botStateFor } from "../bots/config";
import MicWave from "./MicWave";
import { useApp } from "../AppContext";
import type { ActivityMode } from "../AppContext";
import { useCommandHandlers } from "../commands/useCommand";
import { useChatStreamActions } from "../stream/context";
import { exportWAV } from "../utils/audio";
import { api } from "../api";
import { resolveScope } from "../lib/scope";
import type { AgentListItem, ModelItem } from "../types";
import {
  PromptInput,
  PromptInputAction,
  PromptInputActions,
  PromptInputTextarea,
} from "./prompt-kit/prompt-input";
import { Button } from "../ui/primitives";

async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

const TEXT_ATTACHMENT_RE =
  /\.(txt|md|markdown|csv|tsv|json|jsonl|yaml|yml|toml|ini|xml|html?|py|js|ts|tsx|jsx|sql|log|rst)$/i;

function SlashCommandIcon({ command, size = 15 }: { command: SlashCommand; size?: number }) {
  if (command.artifact === 'word' || command.artifact === 'document') {
    return <FileText size={size} strokeWidth={1.9} />;
  }
  if (command.artifact === 'pptx') {
    return <Presentation size={size} strokeWidth={1.9} />;
  }
  if (command.artifact === 'webpage') {
    return <Globe2 size={size} strokeWidth={1.9} />;
  }
  if (command.artifact === 'code') {
    return <Code2 size={size} strokeWidth={1.9} />;
  }
  if (command.mode === 'moe') {
    return <Users size={size} strokeWidth={1.9} />;
  }
  if (command.mode === 'deep_research' || command.mode === 'default') {
    return command.mode === 'default' ? <Sparkles size={size} strokeWidth={1.9} /> : <Search size={size} strokeWidth={1.9} />;
  }
  return <Sparkles size={size} strokeWidth={1.9} />;
}

/**
 * Build the hidden model prompt for a composer skill. Docx/pptx skills prefer
 * the detailed instructions shipped by the backend skill registry; the local
 * prompt builder is the offline fallback.
 */
async function buildSkillRequest(command: SlashCommand, query: string): Promise<string> {
  const fallback = command.artifact
    ? buildArtifactPrompt(command.artifact, query)
    : query;
  if (!command.skillId) return fallback;
  try {
    const resolved = await api.agents.skillsAdmin.resolve(
      `${command.command} ${query}`.trim(),
    );
    const instructions = resolved.skill?.instructions?.trim();
    if (resolved.resolved && instructions) {
      return [
        instructions,
        "",
        "USER REQUEST",
        query,
        ...(command.artifact
          ? [
              "",
              "Return the single fenced artifact now. Do not call any tool and do not narrate the instructions.",
            ]
          : []),
      ].join("\n");
    }
  } catch {
    // Offline or an older backend: use the local prompt.
  }
  return fallback;
}

interface InputAreaProps {
  /** Send a plain message through a channel/team instead of the chat stream. */
  onLocalSend?: (text: string) => Promise<void> | void;
  placeholder?: string;
  disabled?: boolean;
  /** Agents the @ picker may mention. Defaults to every enabled agent. */
  mentionAgents?: AgentListItem[];
}

function InputArea({
  onLocalSend,
  placeholder = "Ask me anything...",
  disabled = false,
  mentionAgents,
}: InputAreaProps = {}) {
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
    activeProjectId,
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
  const scope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  // A quoted message the next send replies to. Set by the message row.
  const [replyTarget, setReplyTarget] = useState<
    { messageId?: number; author: string; content: string } | null
  >(null);
  // When set, the next handleSend() uses this text instead of the composer
  // value. Used by the "regenerate" command to replay a previous message.
  const sendOverrideRef = useRef<string | null>(null);
  // Guards the async attachment upload window, before isGenerating flips.
  const sendingRef = useRef(false);

  const [moePopupOpen, setMoePopupOpen] = useState(false);
  const [burstNonce, fireBurst] = useOneShot();
  const moeBtnRef = useRef<HTMLButtonElement>(null);
  const moePopupRef = useRef<HTMLDivElement>(null);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [popupPos, setPopupPos] = useState<{ top?: number; bottom?: number; left: number } | null>(null);
  const [allAgents, setAllAgents] = useState<AgentListItem[]>([]);
  // Installed backend skills expose their own slash commands (for example an
  // installed /meeting or /release-notes skill). Built-in composer commands
  // win when a command name overlaps.
  const [extraSkills, setExtraSkills] = useState<SlashCommand[]>([]);
  const [mention, setMention] = useState<MentionToken | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [slash, setSlash] = useState<SlashToken | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  // Selecting /docx or /pptx arms a skill; the next message is the query.
  const pendingSkillRef = useRef<SlashCommand | null>(null);
  const [pendingSkill, setPendingSkill] = useState<SlashCommand | null>(null);
  const [localBusy, setLocalBusy] = useState(false);
  const [officeJob, setOfficeJob] = useState<OfficeJob | null>(null);
  const officeJobId = useRef(0);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const pcmRef = useRef<Float32Array[]>([]);
  const levelRef = useRef(0);

  useEffect(() => {
    const load = () =>
      api.agents
        .list()
        .then((d) => setAllAgents((d.agents || []).filter((a) => a.enabled)))
        .catch(() => {});
    void load();
    window.addEventListener('palimind:agents-changed', load);
    return () => window.removeEventListener('palimind:agents-changed', load);
  }, []);

  useEffect(() => {
    api.agents.skillsAdmin
      .commands()
      .then((data) => {
        const builtIn = new Set(SLASH_COMMANDS.map((item) => item.command.toLowerCase()));
        setExtraSkills(
          (data.commands || [])
            .filter((item) => !builtIn.has(item.command.toLowerCase()))
            .map((item) => ({
              id: `skill:${item.skill_id}`,
              command: item.command,
              label: item.name,
              description: item.description,
              keywords: [item.category, 'skill'],
              skillId: item.skill_id,
            })),
        );
      })
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

  // Release the microphone if the composer unmounts mid-recording (e.g. the
  // user switches views), otherwise the input stream stays open.
  useEffect(() => {
    return () => {
      if (!mediaStreamRef.current && !audioCtxRef.current) return;
      try {
        processorRef.current?.disconnect();
        sourceNodeRef.current?.disconnect();
      } catch {
        // ignore
      }
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
      void audioCtxRef.current?.close().catch(() => {});
      audioCtxRef.current = null;
      processorRef.current = null;
      sourceNodeRef.current = null;
      pcmRef.current = [];
      levelRef.current = 0;
      setIsRecording(false);
    };
  }, [setIsRecording]);

  const mentionPool = mentionAgents ?? allAgents;
  const mentionMatches = mention
    ? mentionPool.filter((a) =>
        a.name.toLowerCase().includes(mention.query.toLowerCase()) ||
        (a.display_name || "").toLowerCase().includes(mention.query.toLowerCase()),
      )
    : [];

  const applyMention = useCallback(
    (agentName: string) => {
      if (!mention) return;
      const result = applyAgentMention(value, mention, agentName);
      setValue(result.text);
      setMention(null);
      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) return;
        textarea.focus();
        textarea.setSelectionRange(result.cursor, result.cursor);
      });
    },
    [mention, value],
  );

  const updateMention = useCallback((text: string, cursor = text.length) => {
    const token = findMentionToken(text, cursor);
    setMention(token);
    if (token) setMentionIndex(0);
  }, []);

  const slashCommands = useMemo(
    () => [...SLASH_COMMANDS, ...extraSkills],
    [extraSkills],
  );
  const slashMatches = slash ? filterSlashCommands(slash.query, slashCommands) : [];
  const activeCommand = useMemo(
    () => leadingCommand(value, slashCommands),
    [value, slashCommands],
  );
  const commandQuery = activeCommand
    ? value.replace(/^\s*[/\\][\w-]+\s*/, '').trim()
    : '';

  const updateSlash = useCallback((text: string, cursor = text.length) => {
    // Don't open the slash menu inside an @agent mention.
    if (findMentionToken(text, cursor)) {
      setSlash(null);
      return;
    }
    const token = findSlashToken(text, cursor);
    setSlash(token);
    if (token) setSlashIndex(0);
  }, []);

  const applySlash = useCallback(
    (command: SlashCommand) => {
      if (!slash) return;
      if (command.artifact || command.skillId) {
        // Keep the command in the composer so the user can see and edit what
        // will run. The transcript keeps the same text; the detailed skill
        // prompt is still assembled only at send time.
        const result = insertSlashCommand(value, slash, command);
        pendingSkillRef.current = null;
        setPendingSkill(null);
        setSlash(null);
        setValue(result.text);
        requestAnimationFrame(() => {
          const textarea = textareaRef.current;
          if (!textarea) return;
          textarea.focus();
          textarea.setSelectionRange(result.cursor, result.cursor);
        });
        return;
      }
      // Mode commands switch the runtime immediately; they are not sent as
      // text to the model, so the token is removed from the query.
      const cleaned = stripSlashToken(value, slash);
      pendingSkillRef.current = null;
      setPendingSkill(null);
      setValue(cleaned);
      if (command.mode) {
        void handleSubModeChange(command.mode);
      }
      requestAnimationFrame(() => textareaRef.current?.focus());
    },
    // handleSendRef/handleSubModeChange are declared below but stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [slash, value],
  );
  const isEmpty = !value.trim() && attachedFiles.length === 0;
  const showStop = !onLocalSend && isGenerating;
  const sendDisabled = disabled || (onLocalSend ? localBusy : false) || isEmpty;
  const composerPlaceholder = pendingSkill
    ? "Describe what you need..."
    : activeCommand && !commandQuery
      ? `Describe the ${activeCommand.label.toLowerCase()} you need...`
      : placeholder;

  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

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
    if (onLocalSend) {
      const text = value.trim();
      if (!text || localBusy || disabled) return;
      setLocalBusy(true);
      setValue("");
      setMention(null);
      setSlash(null);
      try {
        await onLocalSend(text);
      } catch (e) {
        addToast(e instanceof Error ? e.message : "Could not send message", { tone: "error" });
      } finally {
        setLocalBusy(false);
      }
      return;
    }
    if (activeView === "agents" && selectedAgentId && isGenerating && !sendingRef.current) {
      const text = value.trim();
      if (!text) return;
      sendingRef.current = true;
      setLocalBusy(true);
      try {
        const result = await api.agents.send(selectedAgentId, text, {
          threadId: activeSessionId || undefined,
          clientMessageId: `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          expectsReply: true,
        });
        if (result.error) {
          addToast(result.error, { tone: "error" });
          return;
        }
        setValue("");
        setReplyTarget(null);
        addToast("Queued — the agent will pick this up next.", { tone: "success" });
        window.dispatchEvent(new CustomEvent("palimind:agents-changed"));
      } catch (e) {
        addToast(e instanceof Error ? e.message : "Could not queue the message", { tone: "error" });
      } finally {
        setLocalBusy(false);
        sendingRef.current = false;
      }
      return;
    }
    if (isGenerating || sendingRef.current || disabled) return;
    const override = sendOverrideRef.current;
    sendOverrideRef.current = null;
    // A replayed message (regenerate / edit-and-resend) must not consume the
    // user's in-progress draft or attachments.
    const fromComposer = override === null;
    const files = fromComposer ? attachedFiles : [];
    const text = (override ?? value).trim();
    if (!text && files.length === 0) return;

    const exactSkill = fromComposer
      ? slashCommands.find(
          (item) =>
            (item.artifact || item.skillId) &&
            item.command.toLowerCase() === text.replace(/^\\/, '/').toLowerCase(),
        )
      : null;
    if (exactSkill) {
      // The command stays in the composer: the user still needs to say what
      // the document or deck should be about.
      setSlash(null);
      addToast(`Add a topic after ${exactSkill.command}.`);
      requestAnimationFrame(() => textareaRef.current?.focus());
      return;
    }

    // A skill selected in the composer is visible in the transcript, but the
    // model receives the detailed skill prompt instead of the raw command.
    const pending = fromComposer ? pendingSkillRef.current : null;
    pendingSkillRef.current = null;
    setPendingSkill(null);
    const direct = parseArtifactCommand(text, slashCommands);
    const activeSkill = pending ?? direct?.command ?? null;
    const skillQuery = pending ? text : (direct?.query ?? "");
    let visibleText = text;
    let modelText = text;

    sendingRef.current = true;
    try {
      if (activeSkill) {
        if (!skillQuery) {
          addToast("Add a topic after the skill command.");
          return;
        }
        const option = CREATE_ARTIFACT_OPTIONS.find(
          (item) => item.kind === activeSkill.artifact,
        );
        if (option?.officeFormat) {
          officeJobId.current += 1;
          setOfficeJob({
            format: option.officeFormat,
            title: option.label,
            id: officeJobId.current,
          });
        }
        modelText = await buildSkillRequest(activeSkill, skillQuery);
        visibleText = pending
          ? `${activeSkill.command} ${skillQuery}`.trim()
          : text;
      }
      // Upload attachments for multimodal chat (images/PDFs/text). Separately,
      // index text-like files as captures so document-mode RAG can find them.
      const attachmentIds: string[] = [];
      if (files.length > 0) {
        const uploaded = await Promise.all(
          files.map(async (file) => {
            try {
              const data = await fileToBase64(file);
              const res = await api.uploads.create(
                file.name,
                file.type || "application/octet-stream",
                data,
              );
              if (res.error) {
                addToast(`${file.name}: ${res.error}`);
                return null;
              }
              return res.upload?.id ?? null;
            } catch (e) {
              addToast(
                `${file.name}: ${e instanceof Error ? e.message : String(e)}`,
              );
              return null;
            }
          }),
        );
        attachmentIds.push(...uploaded.filter((id): id is string => Boolean(id)));

        const textFiles = files.filter(
          (file) => file.type.startsWith("text/") || TEXT_ATTACHMENT_RE.test(file.name),
        );
        if (textFiles.length > 0) {
          try {
            await Promise.all(
              textFiles.map(async (file) => {
                const content = await file.text();
                await fetch("/api/capture/file", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ name: file.name, content }),
                });
              }),
            );
          } catch (e) {
            console.error("attachment capture upload failed:", e);
          }
        }
      }

      if (fromComposer) {
        setValue("");
        setAttachedFiles([]);
        setReplyTarget(null);
      }

      // ── activity-chain metadata (same shell for every mode) ───────────
      const agentInfo = selectedAgentId
        ? allAgents.find((a) => a.id === selectedAgentId)
        : undefined;
      let actMode: ActivityMode = "llm";
      let actTitle = "LLM";
      if (activeView === "agents") {
        actMode = "agent";
        actTitle = agentInfo?.display_name || agentInfo?.name || "Agent";
      } else if (chatMode === "document") {
        actMode = "document";
        actTitle = "Document";
      } else if (activeSkill) {
        actMode = "llm";
        actTitle = "LLM";
      } else if (llmSubMode === "moe") {
        actMode = "moe";
        actTitle = "Mixture of Experts";
      } else if (llmSubMode === "deep_research") {
        actMode = "deep_research";
        actTitle = "Deep Research";
      }

      // A mention anywhere in the message routes the turn to that agent, even
      // in the Agents view. The activity avatar must follow the responder.
      const mentionedName = firstAgentMention(visibleText);
      const mentionedAgent = mentionedName
        ? allAgents.find((a) => a.name === mentionedName)
        : undefined;
      const agentLoading = mentionedAgent
        ? {
            seed: mentionedAgent.id,
            name: mentionedAgent.name,
          }
        : null;

      // The avatar shown while the agent answers: the @mentioned agent wins,
      // otherwise the selected agent in the Agents view.
      const activityAgent =
        mentionedAgent || (actMode === "agent" && agentInfo ? agentInfo : undefined);
      if (mentionedAgent && actMode === "agent") {
        actTitle = mentionedAgent.display_name || mentionedAgent.name;
      }

      const mode = isChatView ? "llm" : chatMode;

      sendMessage({
        text: modelText,
        userText: visibleText || "Sent attachments.",
        mode,
        scope,
        sessionId: activeSessionId,
        subMode: mode === "llm" ? (activeSkill ? "default" : llmSubMode) : undefined,
        // Search is part of every turn now; there is no composer toggle.
        webSearch: true,
        displayText: activeSkill ? visibleText : undefined,
        files: selectedFiles.size > 0 ? Array.from(selectedFiles) : undefined,
        attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
        replyTo: isChatView ? replyTarget?.messageId : undefined,
        activity: {
          mode: actMode,
          title: actTitle,
          subtitle: actMode === "agent" ? "agent" : undefined,
          seed: activityAgent ? activityAgent.id : undefined,
          agentAvatar: activityAgent
            ? {
                config: activityAgent.avatar_config,
                type: activityAgent.avatar_type,
                upload: activityAgent.avatar_upload,
              }
            : undefined,
        },
        agentLoading,
      });
    } finally {
      sendingRef.current = false;
    }
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
    onLocalSend,
    localBusy,
    disabled,
    slashCommands,
    sendMessage,
    addToast,
    replyTarget?.messageId,
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

  // Surfaces can pre-fill the composer (e.g. "continue" actions).
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail?.text as string | undefined;
      if (typeof text !== 'string') return;
      setValue(text);
      requestAnimationFrame(() => textareaRef.current?.focus());
    };
    const agentHandler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { messageId?: number; author?: string; content?: string }
        | undefined;
      if (!detail?.content) return;
      setReplyTarget({
        messageId: detail.messageId,
        author: detail.author || 'message',
        content: detail.content,
      });
      requestAnimationFrame(() => textareaRef.current?.focus());
    };
    window.addEventListener('palimind:prefill-composer', handler);
    window.addEventListener('palimind:agent-prefill', handler);
    window.addEventListener('palimind:agent-reply', agentHandler);
    return () => {
      window.removeEventListener('palimind:prefill-composer', handler);
      window.removeEventListener('palimind:agent-prefill', handler);
      window.removeEventListener('palimind:agent-reply', agentHandler);
    };
  }, []);

  useEffect(() => {
    setReplyTarget(null);
  }, [activeSessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Enter while an IME is composing confirms the candidate; never submit.
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Escape" && pendingSkillRef.current) {
      e.preventDefault();
      pendingSkillRef.current = null;
      setPendingSkill(null);
      setValue("");
      return;
    }
    if (slash && slashMatches.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIndex((i) => (i + 1) % slashMatches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIndex((i) => (i - 1 + slashMatches.length) % slashMatches.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        applySlash(slashMatches[slashIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlash(null);
        return;
      }
    }
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

  const isAdvancedMode = chatMode === "llm" && llmSubMode !== "default";
  const selectedAgent =
    activeView === "agents" && selectedAgentId
      ? allAgents.find((agent) => agent.id === selectedAgentId)
      : undefined;
  const modeLabel =
    llmSubMode === "moe"
      ? "Mixture of Experts"
      : llmSubMode === "deep_research"
        ? "Deep Research"
        : "Default";

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



      {replyTarget && (
        <div className="composer-reply-chip" role="status">
          <span className="composer-reply-chip__label">Replying to {replyTarget.author}</span>
          <span className="composer-reply-chip__text">
            {replyTarget.content.replace(/\s+/g, " ").slice(0, 120)}
          </span>
          <button
            type="button"
            aria-label="Cancel reply"
            onClick={() => setReplyTarget(null)}
          >
            ×
          </button>
        </div>
      )}

      <PromptInput
        className="ai-command-center"
        id="ai-command-center"
        value={value}
        onValueChange={(nextValue) => {
          setValue(nextValue);
          updateMention(nextValue);
          updateSlash(nextValue);
        }}
        isLoading={showStop}
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

        {activeCommand && (activeCommand.artifact || activeCommand.skillId) && (
          <div
            className="composer-command-chip"
            role="status"
            title={`${activeCommand.command} · ${activeCommand.description}`}
          >
            <span className="composer-command-chip__icon">
              <SlashCommandIcon command={activeCommand} size={14} />
            </span>
            <code className="composer-command-chip__name">{activeCommand.command}</code>
            <span className="composer-command-chip__label">{activeCommand.label}</span>
            <span className="composer-command-chip__hint">
              {commandQuery ? 'Press send to generate' : 'Add a topic, then send'}
            </span>
            <button
              type="button"
              className="composer-command-chip__remove"
              aria-label={`Remove ${activeCommand.command}`}
              title="Remove command"
              onClick={() => {
                const next = removeLeadingCommand(value, activeCommand.command);
                setValue(next);
                requestAnimationFrame(() => {
                  const textarea = textareaRef.current;
                  if (!textarea) return;
                  textarea.focus();
                  textarea.setSelectionRange(next.length, next.length);
                });
              }}
            >
              ×
            </button>
          </div>
        )}

        {slash && (
          <div className="slash-command-popup" role="listbox" aria-label="Slash commands">
            <div className="slash-command-head">
              <span className="slash-command-head__title">Commands</span>
              <span className="slash-command-head__query">
                {slash.query ? `/${slash.query}` : 'Start typing to filter'}
              </span>
            </div>
            {slashMatches.length === 0 && (
              <div className="agent-mention-empty">No matching commands</div>
            )}
            {slashMatches.map((command, index) => (
              <div
                key={command.id}
                role="option"
                aria-selected={index === slashIndex}
                className={`slash-command-item${index === slashIndex ? " selected" : ""}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  applySlash(command);
                }}
                onMouseEnter={() => setSlashIndex(index)}
              >
                <span className={`slash-command-icon slash-command-icon--${command.artifact ?? (command.mode ? 'mode' : 'skill')}`}>
                  <SlashCommandIcon command={command} />
                </span>
                <span className="slash-command-info">
                  <span className="slash-command-top">
                    <span className="slash-command-name">{command.command}</span>
                    <span className="slash-command-label">{command.label}</span>
                  </span>
                  <span className="slash-command-desc">{command.description}</span>
                </span>
                <span className="slash-command-badge">{commandBadge(command)}</span>
              </div>
            ))}
            <div className="slash-command-foot">
              <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
              <span><kbd>↵</kbd> insert</span>
              <span><kbd>esc</kbd> close</span>
            </div>
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
                <AgentAvatar
                  config={a.avatar_config}
                  type={a.avatar_type === 'upload' ? 'upload' : 'bot'}
                  upload={a.avatar_upload}
                  state={botStateFor(a)}
                  size={20}
                />
                <span className="agent-mention-name">
                  {a.display_name || a.name}
                  <span className="agent-mention-handle">@{a.name}</span>
                </span>
              </div>
            ))}
          </div>
        )}

        <ComposerCaption />
        <PromptInputTextarea
          id="chat-input"
          ref={textareaRef}
          rows={1}
          aria-label="Chat message"
          placeholder={composerPlaceholder}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            const cursor = e.currentTarget.selectionStart ?? e.target.value.length;
            updateMention(e.target.value, cursor);
            updateSlash(e.target.value, cursor);
          }}
          onKeyDown={handleKeyDown}
        />

        <div className="composer-footer">
          {chatMode === "llm" && activeView !== "agents" && (
            <>
            <div className="moe-toggle-wrapper">
              <button
                ref={moeBtnRef}
                type="button"
                className={`moe-toggle-btn${isAdvancedMode ? " moe-active" : ""}`}
                onClick={() => setMoePopupOpen(!moePopupOpen)}
              >
                <span className="moe-btn-label">
                  {modeLabel}
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
                      <span className="moe-popup-option-name">Deep Research</span>
                      <span className="moe-popup-option-desc">
                        Plan, research in parallel, then write a cited report
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
            </>
          )}

          {activeView === "agents" ? (
            <ModelPicker
              value={selectedAgent?.model || ""}
              placeholder="Choose model"
              variant="composer"
              placement="up"
              onChange={(model, provider) => {
                if (!selectedAgentId) return;
                const nextProvider = provider || selectedAgent?.provider || "ollama";
                void api.agents
                  .update(selectedAgentId, { model, provider: nextProvider })
                  .then(() => window.dispatchEvent(new CustomEvent("palimind:agents-changed")))
                  .catch(() => undefined);
              }}
            />
          ) : (
            <ModelSwitcher />
          )}

          {burstNonce > 0 && (
            <PixelBurst key={burstNonce} className="composer-burst" />
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
              tooltip={showStop ? "Stop generation" : "Send message"}
            >
              <Button
                id="btn-send"
                type="button"
                variant="ghost"
                size="icon"
                aria-label={showStop ? "Stop generating" : "Send message"}
                className={`send-btn${showStop ? " animating-stop" : ""}`}
                disabled={!showStop && sendDisabled}
                onClick={() => {
                  if (showStop) {
                    stopStream();
                  } else {
                    fireBurst();
                    handleSend();
                  }
                }}
              >
                {showStop ? (
                  <Square className="stop-icon" aria-hidden="true" />
                ) : (
                  <ArrowUp className="send-icon" aria-hidden="true" />
                )}
              </Button>
            </PromptInputAction>
          </PromptInputActions>
        </div>
      </PromptInput>

      <OfficeExportWatcher job={officeJob} onDone={() => setOfficeJob(null)} />
    </div>
  );
}

// No props: memo keeps the composer from re-rendering when ChatArea re-renders
// on every streamed token. It still updates from AppContext on its own.
export default memo(InputArea);
