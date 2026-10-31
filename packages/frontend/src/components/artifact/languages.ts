import type { ArtifactType } from '../../utils/artifacts';

const LANGUAGE_ALIASES: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  py: 'python',
  rb: 'ruby',
  rs: 'rust',
  yml: 'yaml',
  htm: 'xml',
  html: 'xml',
  sh: 'bash',
  zsh: 'bash',
  shell: 'bash',
};

/** Normalise fence/file language names to ones registered with highlight.js. */
export function normalizeLanguage(language?: string): string {
  const value = (language || '').trim().toLowerCase();
  const aliased = LANGUAGE_ALIASES[value] || value;
  return aliased || 'text';
}

/** Highlight.js language to use for an artifact's source. */
export function sourceLanguage(type: ArtifactType, language?: string): string {
  switch (type) {
    case 'html':
    case 'svg':
      return 'xml';
    case 'react':
      return 'javascript';
    case 'markdown':
    case 'document':
    case 'table':
    case 'slide-outline':
      return 'markdown';
    case 'mermaid':
      return 'text';
    default:
      return normalizeLanguage(language);
  }
}
