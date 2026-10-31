import type { Dispatch, SetStateAction } from 'react';
import type { ActivityMode, ActivityState } from '../AppContext';

export interface ActivityInfo {
  mode: ActivityMode;
  title: string;
  subtitle?: string;
  seed?: string;
  agentAvatar?: ActivityState['agentAvatar'];
}

/**
 * Accumulates the reasoning-chain steps shown by <ActivityChain>. This used to
 * live inline in InputArea's send handler; keeping it as a small stateful
 * helper makes the event switch dramatically easier to read.
 */
export function createActivityTracker(
  setActivity: Dispatch<SetStateAction<ActivityState | null>>,
) {
  let stepSeq = 0;
  const agentStepIds: Record<number, string> = {};

  const newId = () => `st${Date.now().toString(36)}${(stepSeq++).toString(36)}`;

  return {
    reset(info: ActivityInfo) {
      setActivity({ ...info, steps: [] });
    },

    addStep(kind: string, title: string, detail = '') {
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: [
                ...prev.steps,
                { id: newId(), kind, title, detail, status: 'active' as const },
              ],
            }
          : prev,
      );
    },

    completeActive() {
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: prev.steps.map((s) =>
                s.status === 'active' ? { ...s, status: 'done' as const } : s,
              ),
            }
          : prev,
      );
    },

    setActiveDetail(text: string) {
      setActivity((prev) => {
        if (!prev || prev.steps.length === 0) return prev;
        const steps = [...prev.steps];
        const i = steps.length - 1;
        steps[i] = {
          ...steps[i],
          detail: text.length > 2000 ? text.slice(-2000) : text,
        };
        return { ...prev, steps };
      });
    },

    addAgentStep(aid: number, title: string, detail = '') {
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
                  kind: 'agent',
                  title,
                  detail,
                  status: 'active' as const,
                  children: [],
                },
              ],
            }
          : prev,
      );
    },

    completeAgentStep(aid: number) {
      const sid = agentStepIds[aid];
      if (!sid) return;
      setActivity((prev) =>
        prev
          ? {
              ...prev,
              steps: prev.steps.map((s) =>
                s.id === sid ? { ...s, status: 'done' as const } : s,
              ),
            }
          : prev,
      );
    },

    appendAgentChild(aid: number, text: string) {
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
                        { id: newId(), kind: 'thought', title: text, status: 'done' as const },
                      ],
                    }
                  : s,
              ),
            }
          : prev,
      );
    },

    reasonKind(text: string): string {
      const t = text.toLowerCase();
      if (t.includes('document mode') || t.includes('llm mode') || t.includes('deep research mode')) return 'mode';
      if (t.includes('routing')) return 'route';
      if (t.includes('briefing')) return 'briefing';
      if (t.includes('planning') || t.includes('plan') || t.includes('research plan')) return 'plan';
      if (t.includes('graph')) return 'graph';
      if (t.includes('search') || t.includes('research agent')) return 'search';
      if (t.includes('passage') || t.includes('source')) return 'docs';
      if (t.includes('synthesi') || t.includes('research report')) return 'synthesis';
      if (t.includes('verif')) return 'verify';
      if (t.includes('generat')) return 'answer';
      return 'info';
    },
  };
}

export type ActivityTracker = ReturnType<typeof createActivityTracker>;
