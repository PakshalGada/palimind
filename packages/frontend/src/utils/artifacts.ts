/**
 * Artifact detection (1.2).
 *
 * Scans assistant Markdown for fenced code blocks that describe a rich,
 * renderable output (HTML, SVG, Mermaid, React/JSX, Markdown) and turns each
 * into an `Artifact` that the side panel can preview, edit, export or save.
 */

export type ArtifactType = 'html' | 'svg' | 'mermaid' | 'react' | 'markdown' | 'code';

export interface Artifact {
  /** Stable id derived from type + content. */
  id: string;
  type: ArtifactType;
  /** The raw fence language as written (e.g. `tsx`). */
  language: string;
  title: string;
  content: string;
  /** Index of the source message within the session. */
  messageIndex: number;
}

const LANGUAGE_MAP: Record<string, ArtifactType> = {
  html: 'html',
  htm: 'html',
  svg: 'svg',
  mermaid: 'mermaid',
  mmd: 'mermaid',
  react: 'react',
  jsx: 'react',
  tsx: 'react',
  markdown: 'markdown',
  md: 'markdown',
};

/** djb2 → base36, good enough for stable client-side ids. */
function hashString(input: string): string {
  let hash = 5381;
  for (let i = 0; i < input.length; i++) {
    hash = ((hash << 5) + hash) ^ input.charCodeAt(i);
  }
  return (hash >>> 0).toString(36);
}

function deriveTitle(type: ArtifactType, language: string, content: string): string {
  const firstHeading = content.match(/^\s*#{1,6}\s+(.+)$/m)?.[1]?.trim();
  if (firstHeading) return firstHeading.slice(0, 60);
  if (type === 'html') {
    const title = content.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim();
    if (title) return title.slice(0, 60);
  }
  const label =
    type === 'code' ? language || 'Code' : type.charAt(0).toUpperCase() + type.slice(1);
  return `${label} artifact`;
}

const FENCE_RE = /```([^\n`]*)\n([\s\S]*?)```/g;

export function parseArtifacts(markdown: string, messageIndex = 0): Artifact[] {
  const artifacts: Artifact[] = [];
  if (!markdown) return artifacts;

  let match: RegExpExecArray | null;
  FENCE_RE.lastIndex = 0;
  while ((match = FENCE_RE.exec(markdown)) !== null) {
    const rawLang = match[1].trim().toLowerCase();
    const language = rawLang.split(/\s+/)[0] || '';
    const content = match[2].replace(/\s+$/, '');
    if (!content.trim()) continue;
    const type = LANGUAGE_MAP[language];
    if (!type) continue; // only rich/recognised artifacts are surfaced
    artifacts.push({
      id: `${type}-${hashString(`${type}:${content}`)}`,
      type,
      language,
      title: deriveTitle(type, language, content),
      content,
      messageIndex,
    });
  }
  return artifacts;
}

export interface ArtifactSource {
  role: string;
  content: string;
}

/** Collect artifacts from the assistant messages of a conversation. */
export function collectArtifacts(messages: ArtifactSource[] | undefined): Artifact[] {
  if (!messages?.length) return [];
  const out: Artifact[] = [];
  const seen = new Set<string>();
  messages.forEach((msg, index) => {
    if (msg.role === 'user') return;
    for (const artifact of parseArtifacts(msg.content || '', index)) {
      if (seen.has(artifact.id)) continue;
      seen.add(artifact.id);
      out.push(artifact);
    }
  });
  return out;
}

export const ARTIFACT_TYPE_LABEL: Record<ArtifactType, string> = {
  html: 'HTML',
  svg: 'SVG',
  mermaid: 'Mermaid',
  react: 'React',
  markdown: 'Markdown',
  code: 'Code',
};

export const ARTIFACT_EXTENSION: Record<ArtifactType, string> = {
  html: 'html',
  svg: 'svg',
  mermaid: 'mmd',
  react: 'jsx',
  markdown: 'md',
  code: 'txt',
};

export function downloadArtifact(
  artifact: Pick<Artifact, 'type' | 'title' | 'content'>,
): void {
  const ext = ARTIFACT_EXTENSION[artifact.type];
  const blob = new Blob([artifact.content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${artifact.title.replace(/[^\w.-]+/g, '_') || 'artifact'}.${ext}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
