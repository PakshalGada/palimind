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
