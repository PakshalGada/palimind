import type { AppView } from '../types';

/**
 * The scope a surface reads and writes chat/config data in.
 *
 * This is the single source of truth. Every component that loads sessions,
 * switches models or saves config must go through `resolveScope` so the same
 * view never talks to two different scopes.
 */
export type ChatScope = '' | 'chat' | 'field' | `agent:${string}` | `project:${string}`;

export interface ScopeContext {
  agentId?: string | null;
  projectId?: string | null;
}

export function resolveScope(view: AppView, context: ScopeContext = {}): ChatScope {
  const { agentId, projectId } = context;
  // An agent's chat is private: no agent selected means no scope, never the
  // global chat. This is deliberate.
  if (view === 'agents') {
    return agentId ? `agent:${agentId}` : '';
  }
  if (view === 'chat' || view === 'home') {
    return projectId ? `project:${projectId}` : 'chat';
  }
  if (view === 'knowledge') {
    return projectId ? `project:${projectId}` : 'field';
  }
  return '';
}

/** Human label for a scope, used in the top bar and empty states. */
export function scopeLabel(scope: ChatScope): string {
  if (scope.startsWith('project:')) return 'Project';
  if (scope.startsWith('agent:')) return 'Agent';
  if (scope === 'field') return 'Knowledge';
  if (scope === 'chat') return 'Chat';
  return 'Workspace';
}
