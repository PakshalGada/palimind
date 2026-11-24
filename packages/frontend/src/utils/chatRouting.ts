export type ChatSubMode = 'default' | 'moe' | 'deep_research';

const RESEARCH_RE =
  /\b(research|sources?|cite|citation|literature|survey|deep dive|investigate|fact[- ]?check|web search|browse)\b/i;
const COMPLEX_RE =
  /\b(analy[sz]e|compare|trade[- ]?offs?|strategy|strategic|critique|multiple perspectives|plan|roadmap|architecture|migration|evaluate)\b/i;

export function routeChatSubMode(
  text: string,
  requested: ChatSubMode,
  auto: boolean,
): ChatSubMode {
  if (!auto || requested !== 'default') return requested;
  const clean = text.trim();
  if (!clean) return requested;
  if (RESEARCH_RE.test(clean)) return 'deep_research';
  if (clean.length >= 420 || COMPLEX_RE.test(clean)) return 'moe';
  return 'default';
}

export function routeLabel(mode: ChatSubMode): string {
  if (mode === 'moe') return 'Council';
  if (mode === 'deep_research') return 'Deep Research';
  return 'Default';
}
