import type { DeckChart } from '../../utils/deckPlan';

const SERIES_COLORS = ['#2563eb', '#7c3aed', '#0d9488', '#d97706', '#be123c'];

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = magnitude / 2;
  return Math.ceil(value / step) * step;
}

function formatValue(value: number, unit?: string): string {
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  const prefix = unit?.startsWith('$') ? '$' : '';
  const suffix = unit ? unit.replace(/^\$/, '') : '';
  return `${prefix}${rounded}${suffix}`;
}

function arcPath(cx: number, cy: number, r: number, start: number, end: number): string {
  const large = end - start > Math.PI ? 1 : 0;
  const x1 = cx + r * Math.cos(start);
  const y1 = cy + r * Math.sin(start);
  const x2 = cx + r * Math.cos(end);
  const y2 = cy + r * Math.sin(end);
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
}

export default function SlideChart({
  chart,
  compact = false,
}: {
  chart: DeckChart;
  compact?: boolean;
}) {
  const values = chart.values;
  if (values.length === 0) {
    return <div className="deck-chart-empty">No chart data</div>;
  }

  if (chart.kind === 'pie' || chart.kind === 'donut') {
    const total = values.reduce((sum, value) => sum + Math.max(0, value), 0) || 1;
    let cursor = -Math.PI / 2;
    const cx = compact ? 300 : 360;
    const cy = 240;
    const outer = compact ? 175 : 205;
    const inner = chart.kind === 'donut' ? outer * 0.56 : 0;
    return (
      <div className="deck-chart deck-chart--pie">
        <svg viewBox="0 0 1200 480" role="img" aria-label={chart.title || 'Chart'}>
          {values.map((value, index) => {
            const sweep = (Math.max(0, value) / total) * Math.PI * 2;
            const start = cursor;
            const end = cursor + sweep;
            cursor = end;
            return (
              <path
                key={`${chart.categories[index]}-${index}`}
                d={arcPath(cx, cy, outer, start, end)}
                fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                stroke="#fff"
                strokeWidth="2"
              />
            );
          })}
          {inner > 0 && <circle cx={cx} cy={cy} r={inner} fill="var(--deck-surface, #fff)" />}
          {!compact &&
            values.map((value, index) => {
              const pct = Math.round((Math.max(0, value) / total) * 100);
              const y = 140 + index * 40;
              return (
                <g key={`legend-${index}`}>
                  <rect
                    x="760"
                    y={y - 14}
                    width="18"
                    height="18"
                    rx="4"
                    fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                  />
                  <text x="790" y={y} className="deck-chart__label">
                    {chart.categories[index] || `Item ${index + 1}`}
                  </text>
                  <text x="1150" y={y} textAnchor="end" className="deck-chart__value">
                    {pct}%
                  </text>
                </g>
              );
            })}
        </svg>
      </div>
    );
  }

  const max = niceMax(Math.max(...values.map((value) => Math.abs(value)), 1));
  const min = Math.min(0, ...values);
  const left = 170;
  const right = 1150;
  const top = 45;
  const bottom = 415;
  const width = right - left;
  const height = bottom - top;
  const slot = width / Math.max(1, values.length);
  const barWidth = Math.min(88, slot * 0.58);
  const yOf = (value: number) => bottom - ((value - min) / (max - min || 1)) * height;

  const points = values.map((value, index) => {
    const x = left + slot * (index + 0.5);
    return { x, y: yOf(value), value };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(' ');
  const area = `M ${points[0]?.x ?? left} ${bottom} ${points
    .map((point) => `L ${point.x} ${point.y}`)
    .join(' ')} L ${points[points.length - 1]?.x ?? right} ${bottom} Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="deck-chart">
      <svg viewBox="0 0 1200 480" role="img" aria-label={chart.title || 'Chart'}>
        {ticks.map((tick) => {
          const value = min + (max - min) * tick;
          const y = yOf(value);
          return (
            <g key={tick}>
              <line x1={left} y1={y} x2={right} y2={y} className="deck-chart__grid" />
              <text x={left - 14} y={y + 4} textAnchor="end" className="deck-chart__axis">
                {formatValue(value, chart.unit)}
              </text>
            </g>
          );
        })}
        <line x1={left} y1={bottom} x2={right} y2={bottom} className="deck-chart__axis-line" />

        {chart.kind === 'bar' &&
          points.map((point, index) => (
            <g key={`bar-${index}`}>
              <rect
                x={point.x - barWidth / 2}
                y={Math.min(point.y, bottom)}
                width={barWidth}
                height={Math.abs(bottom - point.y)}
                rx="6"
                fill={SERIES_COLORS[0]}
              />
              <text
                x={point.x}
                y={Math.min(point.y, bottom) - 12}
                textAnchor="middle"
                className="deck-chart__value"
              >
                {formatValue(point.value, chart.unit)}
              </text>
            </g>
          ))}

        {(chart.kind === 'line' || chart.kind === 'area') && (
          <>
            {chart.kind === 'area' && <path d={area} className="deck-chart__area" />}
            <polyline points={line} className="deck-chart__line" />
            {points.map((point, index) => (
              <g key={`point-${index}`}>
                <circle cx={point.x} cy={point.y} r="5" className="deck-chart__point" />
                <text x={point.x} y={point.y - 14} textAnchor="middle" className="deck-chart__value">
                  {formatValue(point.value, chart.unit)}
                </text>
              </g>
            ))}
          </>
        )}

        {points.map((point, index) => (
          <text
            key={`category-${index}`}
            x={point.x}
            y={bottom + 32}
            textAnchor="middle"
            className="deck-chart__label"
          >
            {chart.categories[index] || ''}
          </text>
        ))}
      </svg>
    </div>
  );
}
