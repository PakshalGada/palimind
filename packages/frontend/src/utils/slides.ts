/** Parse a slide-outline artifact into real slide data. */

export interface Slide {
  title: string;
  bullets: string[];
}

const HEADING_RE = /^#{1,4}\s+(.+)$/;
const SLIDE_HEADING_RE = /^slide\s*\d+\s*[:.-]\s*(.+)$/i;
const BULLET_RE = /^\s*(?:[-*+•]|\d+[.)])\s+/;
const DIVIDER_RE = /^\s*---+$/;

function cleanInline(value: string): string {
  return value.replace(/[*_`]/g, '').trim();
}

/**
 * Supported shapes:
 *
 *   # Slide title
 *   - bullet
 *   - bullet
 *
 *   ---
 *
 *   # Next slide
 *
 * A line like `Slide 2: Roadmap` also starts a slide. Prose before the first
 * heading becomes a title slide rather than being dropped.
 */
export function parseSlides(markdown: string): Slide[] {
  const slides: Slide[] = [];
  let current: Slide | null = null;

  const start = (title: string): Slide => {
    const slide = {
      title: cleanInline(title) || `Slide ${slides.length + 1}`,
      bullets: [] as string[],
    };
    slides.push(slide);
    current = slide;
    return slide;
  };

  for (const raw of markdown.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (DIVIDER_RE.test(line)) {
      current = null;
      continue;
    }
    const heading = line.match(HEADING_RE)?.[1] || line.match(SLIDE_HEADING_RE)?.[1];
    if (heading) {
      start(heading);
      continue;
    }
    if (!current) start(slides.length === 0 ? 'Overview' : `Slide ${slides.length + 1}`);
    const bullet = line.replace(BULLET_RE, '').replace(/^[-*+•]\s*/, '');
    if (bullet.trim()) current!.bullets.push(cleanInline(bullet).slice(0, 400));
  }

  if (slides.length === 0 && markdown.trim()) {
    start('Overview');
  }
  return slides;
}
