import type { ChatContextItem } from '../AppContext';

export interface ContextSummary {
  totalTokens: number;
  contextTokens: number;
  messageTokens: number;
  memoryTokens: number;
  pct: number;
}

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export function summarizePinnedContext(items: ChatContextItem[], limit = 6000): ChatContextItem | null {
  if (items.length < 2) return null;
  const summary = items
    .map(
      (item) =>
        `${item.kind === 'artifact' ? 'Artifact' : 'Message'} — ${item.title}: ${item.content.slice(0, 320)}`,
    )
    .join('\n\n');
  return {
    id: `compacted-${Date.now()}`,
    kind: 'message',
    title: `Compacted context (${items.length} items)`,
    content: summary.slice(0, limit),
    createdAt: Date.now(),
  };
}

export function summarizeContextBudget({
  pinnedContext,
  messages,
  memory,
  budget = 8192,
}: {
  pinnedContext: ChatContextItem[];
  messages: { content: string }[];
  memory: string[];
  budget?: number;
}): ContextSummary {
  const contextTokens = estimateTokens(pinnedContext.map((item) => item.content).join('\n'));
  const messageTokens = estimateTokens(messages.map((item) => item.content).join('\n'));
  const memoryTokens = estimateTokens(memory.join('\n'));
  const totalTokens = contextTokens + messageTokens + memoryTokens;
  return {
    contextTokens,
    messageTokens,
    memoryTokens,
    totalTokens,
    pct: Math.min(100, Math.round((totalTokens / budget) * 100)),
  };
}
