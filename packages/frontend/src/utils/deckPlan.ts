/**
 * Deck planning shared types and a local fallback parser.
 *
 * The authoritative plan comes from `/api/office/deck-plan`, which uses the
 * same Python planner as the PPTX renderer. This module exists so the preview
 * still works while the backend is unavailable and so the UI can render a
 * plan it already has.
 */

export type SlideLayout =
  | 'cover'
  | 'agenda'
  | 'section'
  | 'metrics'
  | 'cards'
  | 'comparison'
  | 'timeline'
  | 'quote'
  | 'closing'
  | 'rows'
  | 'bullets'
  | 'chart';

export interface DeckChart {
  kind: 'bar' | 'line' | 'area' | 'pie' | 'donut';
  title?: string;
  unit?: string;
  categories: string[];
  values: number[];
  series_name?: string;
  raw?: string;
}

export interface DeckSlide {
  title: string;
  bullets: string[];
  layout: SlideLayout;
  subtitle?: string;
  hint?: string;
  chart?: DeckChart | null;
}

export interface DeckPlan {
  title: string;
  subtitle?: string;
  slides: DeckSlide[];
  warnings?: string[];
}

const CHART_RE = /^\[chart:\s*(bar|line|area|pie|donut)\]\s*(.+)$/i;
const HINT_RE = /(?:\[layout:\s*([a-z0-9 _-]+)\]|<!--\s*layout:\s*([a-z0-9 _-]+)\s*-->)/i;
const HEADING_RE = /^#{1,4}\s+(.+)$/;
const SLIDE_HEADING_RE = /^slide\s*\d+\s*[:.-]\s*(.+)$/i;
const BULLET_RE = /^\s*(?:[-*+•]|\d+[.)])\s+(.+)$/;
const DIVIDER_RE = /^\s*-{3,}\s*$/;

function cleanInline(value: string): string {
  return value
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/`/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function splitLabel(value: string): [string, string] {
  const raw = cleanInline(value);
  for (const separator of [':', ' — ', ' – ', ' - ']) {
    const at = raw.indexOf(separator);
    if (at > 0) {
      const label = raw.slice(0, at).trim();
      if (label.length <= 56) return [label, raw.slice(at + separator.length).trim()];
    }
  }
  return [raw, ''];
}

export function parseChart(line: string): DeckChart | null {
  const match = line.trim().match(CHART_RE);
  if (!match) return null;
  const kind = match[1].toLowerCase() as DeckChart['kind'];
  const parts = match[2]
    .split('|')
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 2) return null;

  let titlePart = parts[0];
  let unit = '';
  const unitMatch = titlePart.match(/\(([^)]+)\)\s*$/);
  if (unitMatch) {
    unit = unitMatch[1].trim();
    titlePart = titlePart.slice(0, unitMatch.index).trim();
  }

  const categories: string[] = [];
  const values: number[] = [];
  for (const part of parts.slice(1)) {
    let label = part;
    let valueText = part;
    if (part.includes(':')) {
      const at = part.indexOf(':');
      label = part.slice(0, at);
      valueText = part.slice(at + 1);
    } else if (part.includes('=')) {
      const at = part.indexOf('=');
      label = part.slice(0, at);
      valueText = part.slice(at + 1);
    } else {
      const at = part.lastIndexOf(' ');
      if (at > 0) {
        label = part.slice(0, at);
        valueText = part.slice(at + 1);
      }
    }
    const numericText = valueText.replace(/[^0-9.-]/g, '');
    if (!/\d/.test(numericText)) continue;
    const numeric = Number(numericText);
    if (!Number.isFinite(numeric)) continue;
    categories.push(cleanInline(label).slice(0, 48) || `Item ${categories.length + 1}`);
    values.push(numeric);
  }
  if (!values.length) return null;
  return {
    kind,
    title: cleanInline(titlePart),
    unit,
    categories,
    values,
    series_name: cleanInline(titlePart) || 'Value',
    raw: line.trim(),
  };
}

function inferLayout(
  title: string,
  bullets: string[],
  hint: string,
  chart: DeckChart | null,
  isLast: boolean,
): SlideLayout {
  const cleanedHint = hint.replace(/_/g, ' ').trim().toLowerCase();
  const aliases: Record<string, SlideLayout> = {
    kpi: 'metrics',
    metric: 'metrics',
    metrics: 'metrics',
    stats: 'metrics',
    cards: 'cards',
    comparison: 'comparison',
    compare: 'comparison',
    timeline: 'timeline',
    roadmap: 'timeline',
    agenda: 'agenda',
    quote: 'quote',
    closing: 'closing',
    section: 'section',
    bullets: 'bullets',
    list: 'bullets',
    chart: 'chart',
    graph: 'chart',
  };
  if (cleanedHint && aliases[cleanedHint]) return aliases[cleanedHint];
  if (chart) return 'chart';
  if (bullets.length === 0) return 'section';
  const lowered = ` ${title.toLowerCase()} `;
  if (isLast && /(thank you|questions|the ask|next steps|recommendation|closing)/.test(lowered)) {
    return 'closing';
  }
  if (/(agenda|what we will cover|what we'll cover|contents)/.test(lowered)) return 'agenda';
  const labelled = bullets.filter((bullet) => bullet.includes(':') || bullet.includes(' — ')).length;
  if (/(current vs|before vs|versus| vs |comparison|trade-?offs?)/.test(lowered)) {
    return 'comparison';
  }
  if (
    /(roadmap|timeline|milestones?|quarters?|phases?)/.test(lowered) &&
    bullets.some((bullet) => /^(q[1-4]|h[12]|20\d{2}|phase\s*\d+|week\s*\d+)/i.test(splitLabel(bullet)[0]))
  ) {
    return 'timeline';
  }
  if (bullets.length === 1 && bullets[0].length >= 90) return 'quote';
  const metrics = bullets.filter((bullet) => /\d/.test(bullet) && (bullet.includes(':') || /%|\$|€|£/.test(bullet)));
  if (metrics.length >= 2 && metrics.length >= Math.ceil(bullets.length * 0.6)) return 'metrics';
  if (labelled >= 2 && bullets.length <= 6) return 'cards';
  return bullets.length <= 5 ? 'cards' : 'bullets';
}

export function parseDeckOutline(content: string, fallbackTitle = 'Presentation'): DeckSlide[] {
  const slides: DeckSlide[] = [];
  let title = '';
  let bullets: string[] = [];
  let hint = '';
  let chart: DeckChart | null = null;

  const flush = () => {
    if (!title && bullets.length === 0 && !chart) return;
    slides.push({
      title: cleanInline(title) || `Slide ${slides.length + 1}`,
      bullets,
      layout: inferLayout(title, bullets, hint, chart, false),
      chart,
      hint,
    });
    title = '';
    bullets = [];
    hint = '';
    chart = null;
  };

  for (const raw of content.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const hintMatch = line.match(HINT_RE);
    let markerHint = '';
    let working = line;
    if (hintMatch) {
      markerHint = (hintMatch[1] || hintMatch[2] || '').trim();
      working = line.replace(HINT_RE, '').trim();
      if (!working) {
        hint = markerHint;
        continue;
      }
    }
    if (DIVIDER_RE.test(working)) {
      flush();
      continue;
    }
    const heading = working.match(HEADING_RE)?.[1] || working.match(SLIDE_HEADING_RE)?.[1];
    if (heading) {
      flush();
      title = heading;
      hint = markerHint;
      continue;
    }
    if (markerHint) hint = markerHint;
    if (CHART_RE.test(working)) {
      chart = parseChart(working) ?? chart;
      continue;
    }
    const bullet = working.match(BULLET_RE)?.[1] ?? working.replace(/^>\s*/, '');
    if (bullet.trim()) bullets.push(cleanInline(bullet).slice(0, 400));
  }
  flush();

  if (slides.length === 0 && content.trim()) {
    slides.push({
      title: fallbackTitle,
      bullets: content
        .split('\n')
        .map(cleanInline)
        .filter(Boolean)
        .slice(0, 6),
      layout: 'bullets',
      chart: null,
    });
  }

  // A leading title-only slide is the cover, not a content slide.
  if (slides.length > 1 && slides[0].bullets.length === 0 && !slides[0].chart) {
    slides.shift();
  }
  if (slides.length > 0) {
    const last = slides[slides.length - 1];
    last.layout = inferLayout(last.title, last.bullets, last.hint ?? '', last.chart ?? null, true);
  }
  return slides;
}

export function planDeckLocal(title: string, content: string): DeckPlan {
  return {
    title: title || 'Presentation',
    subtitle: '',
    slides: parseDeckOutline(content, title),
  };
}
