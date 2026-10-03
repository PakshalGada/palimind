import type { CSSProperties } from 'react';
import './thinking.css';

/**
 * One monochrome motion language, many variants.
 *
 * Principle: pure black & white. Depth is expressed with opacity,
 * never hue. Every mark shares the same tempo + easing, but each
 * variant uses a different motion so the surface stays distinct.
 */
export type ThinkingVariant = 'orbit' | 'trace' | 'mesh' | 'ripple' | 'beacon' | 'bars';

interface ThinkingProps {
  variant?: ThinkingVariant;
  size?: number;
  className?: string;
  style?: CSSProperties;
  title?: string;
}

/** Stagger helper — the global motion reset kills inline animation-delay,
 *  so we carry the offset through a custom property instead. */
const at = (seconds: number): CSSProperties => ({ '--d': `${seconds}s` } as CSSProperties);

const ORBIT_DOTS: [number, number][] = [
  [12, 4.5],
  [18.5, 15.75],
  [5.5, 15.75],
];

const MESH_NODES: [number, number, number][] = [
  [12, 12, 2.2],
  [5, 6, 1.4],
  [19, 6, 1.4],
  [4, 16.5, 1.4],
  [20, 16.5, 1.4],
  [12, 20.5, 1.4],
];

const MESH_LINKS: [number, number][] = [
  [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [1, 2], [3, 4],
];

const BAR_HEIGHTS = [4, 9, 6, 11, 5];

function renderVariant(variant: ThinkingVariant) {
  switch (variant) {
    case 'trace':
      return (
        <>
          <circle cx="12" cy="12" r="9" className="tk-track" pathLength={100} />
          <circle cx="12" cy="12" r="9" className="tk-arc" pathLength={100} />
        </>
      );

    case 'mesh':
      return (
        <>
          <g className="tk-links">
            {MESH_LINKS.map(([a, b], i) => (
              <line
                key={i}
                x1={MESH_NODES[a][0]}
                y1={MESH_NODES[a][1]}
                x2={MESH_NODES[b][0]}
                y2={MESH_NODES[b][1]}
                className="tk-link"
              />
            ))}
          </g>
          {MESH_NODES.map(([x, y, r], i) => (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={r}
              className={`tk-dot${i === 0 ? ' tk-dot--core' : ''}`}
              style={at(i * 0.18)}
            />
          ))}
        </>
      );

    case 'ripple':
      return (
        <>
          <circle cx="12" cy="12" r="2.4" className="tk-dot tk-dot--core" />
          {[0, 0.6, 1.2].map((d) => (
            <circle key={d} cx="12" cy="12" r="7" className="tk-ring" style={at(d)} />
          ))}
        </>
      );

    case 'beacon':
      return (
        <>
          <circle cx="12" cy="12" r="3" className="tk-dot tk-dot--core" />
          <circle cx="12" cy="12" r="5" className="tk-halo" />
        </>
      );

    case 'bars':
      return (
        <>
          {BAR_HEIGHTS.map((h, i) => (
            <rect
              key={i}
              x={3 + i * 4}
              y={12 - h / 2}
              width="2.6"
              height={h}
              rx="1.3"
              className="tk-bar"
              style={at(i * 0.12)}
            />
          ))}
        </>
      );

    case 'orbit':
    default:
      return (
        <>
          <circle cx="12" cy="12" r="2.2" className="tk-dot tk-dot--core" />
          <g className="tk-orbit">
            {ORBIT_DOTS.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r="1.7" className="tk-dot" style={at(i * 0.2)} />
            ))}
          </g>
        </>
      );
  }
}

export default function Thinking({
  variant = 'orbit',
  size = 18,
  className = '',
  style,
  title,
}: ThinkingProps) {
  return (
    <span
      className={`tk tk--${variant}${className ? ` ${className}` : ''}`}
      style={{ width: size, height: size, ...style }}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <svg viewBox="0 0 24 24" className="tk-svg">
        {renderVariant(variant)}
      </svg>
    </span>
  );
}
