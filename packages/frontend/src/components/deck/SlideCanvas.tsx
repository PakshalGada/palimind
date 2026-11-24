import type { ReactNode } from 'react';
import type { DeckSlide } from '../../utils/deckPlan';
import SlideChart from './SlideChart';

function splitLabel(value: string): [string, string] {
  const raw = value.replace(/\s+/g, ' ').trim();
  for (const separator of [':', ' — ', ' – ', ' - ']) {
    const at = raw.indexOf(separator);
    if (at > 0) {
      const label = raw.slice(0, at).trim();
      if (label.length <= 64) return [label, raw.slice(at + separator.length).trim()];
    }
  }
  return [raw, ''];
}

function metricOf(value: string): { label: string; value: string; detail: string } | null {
  const [label, detail] = splitLabel(value);
  const source = detail || label;
  const match = source.match(/-?\$?\d[\d.,]*\s?(?:%|x|k|m|b|bn|million|billion|pts?|points?|hrs?|hours?|days?|weeks?|months?|years?)?/i);
  if (!match || !/\d/.test(match[0])) return null;
  return { label, value: match[0].trim(), detail: detail.replace(match[0], '').trim() };
}

function timeOf(value: string): { time: string; text: string } {
  const [label, detail] = splitLabel(value);
  const match = label.match(
    /^(q[1-4]|h[12]|20\d{2}|19\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|phase\s*\d+|week\s*\d+|now|next|later)\b/i,
  );
  if (!match) return { time: '', text: value };
  const rest = label.slice(match[0].length).trim().replace(/^[:—–-]\s*/, '');
  return {
    time: match[0],
    text: detail ? (rest ? `${rest} — ${detail}` : detail) : rest,
  };
}

function columnsForComparison(bullets: string[]) {
  const current: string[] = [];
  const proposed: string[] = [];
  for (const bullet of bullets) {
    if (/^(current|today|now|before|old)\b/i.test(bullet)) {
      current.push(bullet.replace(/^(current|today|now|before|old)\s*:\s*/i, ''));
    } else if (/^(proposed|future|after|next|new)\b/i.test(bullet)) {
      proposed.push(bullet.replace(/^(proposed|future|after|next|new)\s*:\s*/i, ''));
    }
  }
  if (current.length || proposed.length) return { current, proposed };
  const at = Math.ceil(bullets.length / 2);
  return { current: bullets.slice(0, at), proposed: bullets.slice(at) };
}

export default function SlideCanvas({
  slide,
  index,
  total,
  deckTitle,
  compact = false,
}: {
  slide: DeckSlide;
  index: number;
  total: number;
  deckTitle: string;
  compact?: boolean;
}) {
  const bullets = slide.bullets ?? [];
  const chart = slide.chart ?? null;
  const page = `${String(index + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}`;
  const isDark = slide.layout === 'cover' || slide.layout === 'section';

  const top = !isDark && (
    <div className="deck-slide__top">
      <div className="deck-slide__progress" aria-hidden="true">
        <span style={{ width: `${((index + 1) / total) * 100}%` }} />
      </div>
      <span className="deck-slide__eyebrow">{deckTitle}</span>
      <span className="deck-slide__page">{page}</span>
    </div>
  );

  const heading = !isDark && slide.layout !== 'quote' && (
    <div className="deck-slide__heading">
      <h2>{slide.title}</h2>
      {slide.hint && <span className="deck-slide__hint">{slide.hint}</span>}
    </div>
  );

  let body: ReactNode = null;

  if (slide.layout === 'cover') {
    body = (
      <div className="deck-cover">
        <span className="deck-cover__eyebrow">PRESENTATION</span>
        <span className="deck-cover__rule" aria-hidden="true" />
        <h1>{slide.title || deckTitle}</h1>
        <p>{slide.subtitle || bullets[0] || 'A working deck built to move the decision forward.'}</p>
        <span className="deck-cover__page">01</span>
      </div>
    );
  } else if (slide.layout === 'section') {
    body = (
      <div className="deck-section">
        <span className="deck-section__eyebrow">SECTION {String(index + 1).padStart(2, '0')}</span>
        <h1>{slide.title}</h1>
        <span className="deck-section__rule" aria-hidden="true" />
        <span className="deck-section__page">{String(index + 1).padStart(2, '0')}</span>
      </div>
    );
  } else if (slide.layout === 'agenda') {
    body = (
      <ol className="deck-agenda">
        {bullets.slice(0, 6).map((item, position) => {
          const [label, detail] = splitLabel(item);
          return (
            <li key={`${position}-${label}`}>
              <span className="deck-agenda__num">{String(position + 1).padStart(2, '0')}</span>
              <span className="deck-agenda__text">
                <strong>{label}</strong>
                {detail && <small>{detail}</small>}
              </span>
            </li>
          );
        })}
      </ol>
    );
  } else if (slide.layout === 'metrics') {
    const metrics = bullets
      .map(metricOf)
      .filter((metric): metric is { label: string; value: string; detail: string } => Boolean(metric))
      .slice(0, 4);
    body = (
      <div className={`deck-metrics deck-metrics--${Math.max(1, metrics.length)}`}>
        {metrics.map((metric, position) => (
          <div className="deck-metric" key={`${position}-${metric.label}`}>
            <span className="deck-metric__bar" aria-hidden="true" />
            <strong>{metric.value}</strong>
            <span className="deck-metric__label">{metric.label}</span>
            {metric.detail && <small>{metric.detail}</small>}
          </div>
        ))}
      </div>
    );
  } else if (slide.layout === 'cards') {
    body = (
      <div className={`deck-cards deck-cards--${Math.min(4, Math.max(1, bullets.length))}`}>
        {bullets.slice(0, 4).map((item, position) => {
          const [label, detail] = splitLabel(item);
          return (
            <div className="deck-card" key={`${position}-${label}`}>
              <span className="deck-card__edge" aria-hidden="true" />
              <strong>{label}</strong>
              {detail && <p>{detail}</p>}
            </div>
          );
        })}
      </div>
    );
  } else if (slide.layout === 'comparison') {
    const { current, proposed } = columnsForComparison(bullets);
    body = (
      <div className="deck-compare">
        <div className="deck-compare__col deck-compare__col--current">
          <h3>Current</h3>
          <ul>
            {current.map((item, position) => (
              <li key={`${position}-${item}`}>{item}</li>
            ))}
          </ul>
        </div>
        <div className="deck-compare__col deck-compare__col--proposed">
          <h3>Proposed</h3>
          <ul>
            {proposed.map((item, position) => (
              <li key={`${position}-${item}`}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  } else if (slide.layout === 'timeline') {
    body = (
      <ol className="deck-timeline">
        {bullets.slice(0, 5).map((item, position) => {
          const { time, text } = timeOf(item);
          return (
            <li key={`${position}-${item}`}>
              <span className="deck-timeline__dot" aria-hidden="true" />
              <span className="deck-timeline__time">{time || `Step ${position + 1}`}</span>
              <span className="deck-timeline__text">{text || item}</span>
            </li>
          );
        })}
      </ol>
    );
  } else if (slide.layout === 'quote') {
    body = (
      <div className="deck-quote">
        <span className="deck-quote__mark" aria-hidden="true">“</span>
        <blockquote>{bullets[0] || slide.title}</blockquote>
        {slide.title && bullets.length > 0 && <cite>{slide.title}</cite>}
      </div>
    );
  } else if (slide.layout === 'closing') {
    body = (
      <div className="deck-closing">
        <ul>
          {bullets.slice(0, 5).map((item, position) => (
            <li key={`${position}-${item}`}>
              <span className="deck-closing__check" aria-hidden="true">✓</span>
              {item}
            </li>
          ))}
        </ul>
      </div>
    );
  } else if (slide.layout === 'chart' && chart) {
    body = (
      <div className="deck-chart-slide">
        {chart.title && (
          <h3 className="deck-chart-slide__title">
            {chart.title}
            {chart.unit ? ` (${chart.unit})` : ''}
          </h3>
        )}
        <div className="deck-chart-slide__frame">
          <SlideChart chart={chart} compact={compact} />
        </div>
        {bullets.length > 0 && (
          <ul className="deck-chart-slide__takeaways">
            {bullets.slice(0, 3).map((item, position) => (
              <li key={`${position}-${item}`}>{item}</li>
            ))}
          </ul>
        )}
      </div>
    );
  } else {
    body = (
      <ul className={`deck-list deck-list--${slide.layout === 'rows' ? 'rows' : 'bullets'}`}>
        {bullets.slice(0, 8).map((item, position) => (
          <li key={`${position}-${item}`}>{item}</li>
        ))}
      </ul>
    );
  }

  return (
    <article
      className={`deck-slide deck-slide--${slide.layout}${isDark ? ' deck-slide--dark' : ''}${
        compact ? ' is-compact' : ''
      }`}
      aria-label={`Slide ${index + 1} of ${total}: ${slide.title}`}
    >
      {top}
      {heading}
      <div className="deck-slide__body">{body}</div>
      {!isDark && <span className="deck-slide__footer">{deckTitle}</span>}
    </article>
  );
}
