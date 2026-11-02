import { useMemo } from 'react';
import type { ToolStep } from '../model';
import { graphOf } from '../toolOutput';

const SIZE = 190;
const RADIUS = 72;

export default function GraphBody({ step }: { step: ToolStep }) {
  const graph = useMemo(() => graphOf(step.output), [step.output]);
  if (graph.nodes.length === 0) return <div className="act-empty">No results</div>;
  const positions = new Map<string, { x: number; y: number }>();
  graph.nodes.forEach((node, index) => {
    const angle = (index / graph.nodes.length) * Math.PI * 2 - Math.PI / 2;
    positions.set(node.id, {
      x: SIZE / 2 + Math.cos(angle) * RADIUS,
      y: SIZE / 2 + Math.sin(angle) * RADIUS,
    });
  });
  return (
    <div className="act-body act-body--flush">
      <svg
        className="act-graph"
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`${graph.nodes.length} nodes, ${graph.edges.length} connections`}
      >
        {graph.edges.map((edge, index) => {
          const from = positions.get(edge.from);
          const to = positions.get(edge.to);
          if (!from || !to) return null;
          return (
            <line
              key={index}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke="var(--act-hairline)"
              strokeWidth={1}
            />
          );
        })}
        {graph.nodes.map((node) => {
          const position = positions.get(node.id);
          if (!position) return null;
          return (
            <g key={node.id}>
              <circle cx={position.x} cy={position.y} r={3} fill="var(--act-accent)" opacity={0.7} />
              <text
                x={position.x}
                y={position.y - 7}
                textAnchor="middle"
                fontSize={8}
                fill="var(--act-muted)"
              >
                {node.label.length > 14 ? `${node.label.slice(0, 13)}…` : node.label}
              </text>
            </g>
          );
        })}
      </svg>
      <table className="act-table" style={{ background: 'transparent', maxHeight: 140 }}>
        <tbody>
          {graph.edges.slice(0, 20).map((edge, index) => (
            <tr key={index}>
              <td>{edge.from}</td>
              <td className="act-muted">{edge.label ?? 'to'}</td>
              <td>{edge.to}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {graph.nodes.length >= 30 && <div className="act-empty">Showing first 30 nodes</div>}
    </div>
  );
}
