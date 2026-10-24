import type { CitationLink, CitationPayload, CitationSource } from '../types';

/** A clickable timestamp inside a media file (video/audio transcript hit). */
export interface MediaCitation {
  file: string;
  start: number;
  end?: number | null;
  snippet?: string;
}

/** A document/section reference surfaced while streaming. */
export interface TextCitation {
  file: string;
  section?: string;
  snippet?: string;
  chunk_id?: number;
}

export interface VerificationReport {
  passed?: boolean;
  confidence?: number;
  reasoning?: string;
}

export interface ApprovalPrompt {
  agentId: string;
  tool: string;
  args?: unknown;
  confidence?: number;
  reasoning?: string;
}

/** A media timestamp the viewer overlay should jump to. */
export interface VideoTarget {
  file: string;
  start: number;
  end?: number | null;
}

/**
 * Every SSE payload the chat stream can emit, discriminated on `type`.
 * Unknown orchestrator events are normalised to `{ type: 'orchestrator' }`
 * so the UI layer never has to string-match raw payloads.
 */
export type StreamEvent =
  | { type: 'token'; text?: string }
  | { type: 'thinking'; text?: string }
  | { type: 'reasoning'; text?: string }
  | { type: 'sources'; sources?: string[] }
  | { type: 'media_citations'; citations?: MediaCitation[] }
  | { type: 'citations'; citations?: TextCitation[] }
  | ({ type: 'citation_map' } & Partial<CitationPayload>)
  | {
      type: 'agent_progress';
      agent_id: number;
      status?: 'working' | 'complete';
      task?: string;
      label?: string;
    }
  | { type: 'agent_thinking'; agent_id: number; text?: string }
  | { type: 'agent:thought'; text?: string; iteration?: number }
  | { type: 'agent:tool_call'; tool?: string; args?: unknown }
  | { type: 'agent:tool_result'; tool?: string; result?: unknown }
  | { type: 'agent:effort'; level?: string; indicator?: string }
  | {
      type: 'agent:plan';
      plan_id?: string;
      steps?: unknown[];
      mode?: string;
      status?: string;
    }
  | { type: 'agent:verification'; report?: VerificationReport; attempt?: number }
  | { type: 'agent:needs_review'; report?: VerificationReport }
  | {
      type: 'agent:waiting_for_human';
      agent_id?: number | string;
      tool?: string;
      args?: unknown;
      confidence?: number;
      reasoning?: string;
      threshold?: number;
    }
  | { type: 'agent:token'; text?: string; reset?: boolean; stream?: boolean }
  | { type: 'agent:completed'; output?: string; status?: string }
  | { type: 'progress'; text?: string }
  | { type: 'research_plan'; plan_id?: string; plan?: unknown }
  | { type: 'answer_final'; text?: string }
  | { type: 'done' }
  | { type: 'error'; text?: string }
  | { type: 'orchestrator'; data: Record<string, unknown> };

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

/** Everything the live assistant turn needs to render, nothing else. */
export interface StreamState {
  status: StreamStatus;
  /** Echoed user prompt (also used to hide the live turn on session switch). */
  userText: string;
  sessionId: string | null;
  /** Throttled display buffer; the raw buffer is kept by the stream engine. */
  answer: string;
  thinking: string;
  sources: string[];
  mediaCitations: MediaCitation[];
  textCitations: TextCitation[];
  citations: CitationPayload | null;
  approval: ApprovalPrompt | null;
  error: string | null;
  thoughtDuration: string | null;
  answerStarted: boolean;
  /** Bumped on every visible change so consumers can auto-scroll cheaply. */
  revision: number;
}

export const initialStreamState: StreamState = {
  status: 'idle',
  userText: '',
  sessionId: null,
  answer: '',
  thinking: '',
  sources: [],
  mediaCitations: [],
  textCitations: [],
  citations: null,
  approval: null,
  error: null,
  thoughtDuration: null,
  answerStarted: false,
  revision: 0,
};

export type StreamAction =
  | { type: 'start'; userText: string; sessionId: string | null }
  | { type: 'reset' }
  | { type: 'setAnswer'; text: string }
  | { type: 'appendThinking'; text: string }
  | { type: 'setSources'; sources: string[] }
  | { type: 'setMediaCitations'; citations: MediaCitation[] }
  | { type: 'setTextCitations'; citations: TextCitation[] }
  | { type: 'setCitations'; citations: CitationPayload | null }
  | { type: 'setApproval'; approval: ApprovalPrompt | null }
  | { type: 'setDuration'; duration: string }
  | { type: 'answerStarted' }
  | { type: 'error'; text: string }
  | { type: 'finish'; status: 'done' | 'error' };

/** Build a CitationPayload from a citation_map event (fields are optional). */
export function citationPayloadFromEvent(
  event: Partial<CitationPayload> & { type: 'citation_map' },
): CitationPayload {
  return {
    text: event.text,
    citations: (event.citations ?? []) as CitationLink[],
    sources: (event.sources ?? []) as CitationSource[],
    bibliography: event.bibliography ?? '',
    accuracy: event.accuracy ?? 0,
    coverage: event.coverage ?? 0,
    mean_score: event.mean_score ?? 0,
    cited_markers: event.cited_markers ?? [],
  };
}

/** Normalise an untrusted SSE payload into a typed stream event. */
export function parseStreamEvent(raw: unknown): StreamEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Record<string, unknown>;
  const type = data.type;
  if (typeof type !== 'string' || !type) return null;
  if (type.startsWith('orchestrator:')) {
    return { type: 'orchestrator', data };
  }
  return data as unknown as StreamEvent;
}
