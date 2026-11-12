import { parseArtifacts } from './artifacts';
import { parseSlides } from './slides';

export interface OfficeSlide {
  title: string;
  bullets: string[];
}

export interface OfficePayload {
  format: 'docx' | 'pptx';
  title: string;
  content?: string;
  slides?: OfficeSlide[];
}

/**
 * Build an Office payload from an artifact the user is already looking at.
 *
 * The artifact panel and the chat composer share the server-side Office
 * pipeline, so a deck exported from the preview looks identical to a deck
 * downloaded when the turn finished.
 */
export function buildArtifactOfficePayload(
  artifact: { type: string; title: string; content: string },
  format: 'docx' | 'pptx',
): OfficePayload {
  const title = artifact.title || (format === 'pptx' ? 'Presentation' : 'Document');
  if (format === 'docx') {
    return { format, title, content: artifact.content };
  }

  const slides =
    artifact.type === 'slide-outline' || artifact.type === 'document' || artifact.type === 'markdown'
      ? parseSlides(artifact.content)
      : [
          {
            title,
            bullets: artifact.content
              .split('\n')
              .map((line) => line.replace(/^#{1,6}\s*/, '').replace(/^\s*[-*]\s+/, '').trim())
              .filter(Boolean)
              .slice(0, 12),
          },
        ];

  return {
    format,
    title,
    slides: slides.length > 0 ? slides : [{ title, bullets: [] }],
  };
}

/**
 * Pick the document/deck the model just wrote out of a settled answer.
 *
 * The prompt builders ask for exactly one fenced artifact, but models
 * sometimes add prose or a second fence. Word prefers document-shaped
 * artifacts; PowerPoint prefers a slide outline and falls back to parsing
 * headings from the answer.
 */
export function buildOfficePayload(
  format: 'docx' | 'pptx',
  answer: string,
  fallbackTitle = 'Document',
): OfficePayload | null {
  const text = answer.trim();
  if (!text) return null;
  const artifacts = parseArtifacts(text, 0);

  if (format === 'pptx') {
    const deck = artifacts.find((artifact) => artifact.type === 'slide-outline');
    const slides = deck ? parseSlides(deck.content) : parseSlides(text);
    if (slides.length === 0) return null;
    return {
      format,
      title: deck?.title || fallbackTitle,
      slides: slides.map((slide) => ({
        title: slide.title,
        bullets: slide.bullets,
      })),
    };
  }

  const document =
    artifacts.find(
      (artifact) =>
        artifact.type === 'document' ||
        artifact.type === 'markdown' ||
        artifact.type === 'table',
    ) || artifacts[0];
  // Markdown fences are intentionally not artifacts anymore, but the Word
  // export still needs the fence body (not the ``` markers) as its source.
  const markdownFence = text.match(/```(?:markdown|md)\s*\n([\s\S]*?)\n```/i);
  const markdownTitle = markdownFence?.[1]?.match(/^#\s+(.+)$/m)?.[1]?.trim();
  return {
    format,
    title: document?.title || markdownTitle || fallbackTitle,
    content: document?.content || markdownFence?.[1] || text,
  };
}
