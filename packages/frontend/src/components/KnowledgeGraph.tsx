import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DataSet } from 'vis-data';
import { Network } from 'vis-network';
import 'vis-network/styles/vis-network.css';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { GraphData, GraphEdge } from '../types';
import './KnowledgeGraph.css';

const MAX_ENTITIES = 40;

type GraphKind = 'file' | 'entity' | 'section';

interface Palette {
  light: string;
  mid: string;
  dark: string;
  rim: string;
  glow: string;
  label: string;
}

interface SelectionInfo {
  id: string;
  label: string;
  type: string;
  file_path?: string;
  direct: number;
  total: number;
}

interface RendererArgs {
  ctx: CanvasRenderingContext2D;
  x: number;
  y: number;
  state: { selected: boolean; hover: boolean };
  style: { size?: number; opacity?: number };
  label?: string;
}

const TYPE_LABEL: Record<string, string> = {
  file: 'File',
  entity: 'Entity',
  section: 'Section',
};

function kindOf(type: string): GraphKind {
  if (type === 'file') return 'file';
  if (type === 'section') return 'section';
  return 'entity';
}

function paletteFor(kind: GraphKind, isDark: boolean): Palette {
  if (isDark) {
    if (kind === 'file') {
      return {
        light: '#dbeafe',
        mid: '#60a5fa',
        dark: '#1d4ed8',
        rim: '#93c5fd',
        glow: 'rgba(96, 165, 250, 0.34)',
        label: '#dbeafe',
      };
    }
    if (kind === 'section') {
      return {
        light: '#fef3c7',
        mid: '#fbbf24',
        dark: '#b45309',
        rim: '#fcd34d',
        glow: 'rgba(251, 191, 36, 0.3)',
        label: '#fde68a',
      };
    }
    return {
      light: '#ccfbf1',
      mid: '#2dd4bf',
      dark: '#0f766e',
      rim: '#5eead4',
      glow: 'rgba(45, 212, 191, 0.34)',
      label: '#ccfbf1',
    };
  }
  if (kind === 'file') {
    return {
      light: '#eff6ff',
      mid: '#3b82f6',
      dark: '#1e40af',
      rim: '#1d4ed8',
      glow: 'rgba(37, 99, 235, 0.22)',
      label: '#1e3a8a',
    };
  }
  if (kind === 'section') {
    return {
      light: '#fffbeb',
      mid: '#f59e0b',
      dark: '#b45309',
      rim: '#b45309',
      glow: 'rgba(245, 158, 11, 0.2)',
      label: '#92400e',
    };
  }
  return {
    light: '#f0fdfa',
    mid: '#14b8a6',
    dark: '#0f766e',
    rim: '#0f766e',
    glow: 'rgba(20, 184, 166, 0.22)',
    label: '#115e59',
  };
}

function truncate(value: string, max = 28): string {
  const text = String(value || '');
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

/** Draw a shaded sphere plus a compact label pill below it. */
function sphereRenderer(kind: GraphKind, isDark: boolean) {
  const palette = paletteFor(kind, isDark);
  return ({ ctx, x, y, state, style, label }: RendererArgs) => {
    const size = Math.max(7, Number(style.size) || 16);
    const opacity = style.opacity == null ? 1 : Number(style.opacity);
    if (opacity <= 0.01) return {};

    ctx.save();
    ctx.globalAlpha = opacity;

    if (state.selected) {
      const halo = ctx.createRadialGradient(x, y, size * 0.7, x, y, size + 17);
      halo.addColorStop(0, palette.glow);
      halo.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(x, y, size + 17, 0, Math.PI * 2);
      ctx.fill();
    }

    if (state.selected || state.hover) {
      ctx.beginPath();
      ctx.arc(x, y, size + (state.selected ? 5 : 3), 0, Math.PI * 2);
      ctx.lineWidth = state.selected ? 2 : 1.25;
      ctx.strokeStyle = palette.rim;
      ctx.globalAlpha = opacity * (state.selected ? 0.95 : 0.55);
      ctx.stroke();
      ctx.globalAlpha = opacity;
    }

    // Sphere body: a radial gradient gives it a three-dimensional read.
    const body = ctx.createRadialGradient(
      x - size * 0.38,
      y - size * 0.42,
      size * 0.08,
      x,
      y,
      size * 1.06,
    );
    body.addColorStop(0, palette.light);
    body.addColorStop(0.42, palette.mid);
    body.addColorStop(1, palette.dark);
    ctx.shadowColor = palette.glow;
    ctx.shadowBlur = state.selected ? 20 : 9;
    ctx.shadowOffsetY = 2;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fillStyle = body;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    ctx.lineWidth = state.selected ? 2 : 1;
    ctx.strokeStyle = palette.rim;
    ctx.stroke();

    // Specular highlight (clipped to the sphere).
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.clip();
    const spec = ctx.createRadialGradient(
      x - size * 0.42,
      y - size * 0.48,
      0,
      x - size * 0.4,
      y - size * 0.45,
      size * 0.62,
    );
    spec.addColorStop(0, 'rgba(255, 255, 255, 0.78)');
    spec.addColorStop(0.45, 'rgba(255, 255, 255, 0.16)');
    spec.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.beginPath();
    ctx.arc(x - size * 0.4, y - size * 0.45, size * 0.62, 0, Math.PI * 2);
    ctx.fillStyle = spec;
    ctx.fill();
    ctx.restore();

    const text = truncate(label || '', 30);
    let boxWidth = size * 2;
    if (text && opacity > 0.32) {
      ctx.font = `${state.selected ? 700 : 600} 11px Inter, ui-sans-serif, system-ui, sans-serif`;
      const textWidth = ctx.measureText(text).width;
      boxWidth = Math.min(230, textWidth + 14);
      const boxHeight = 17;
      const boxX = x - boxWidth / 2;
      const boxY = y + size + 5;
      roundRect(ctx, boxX, boxY, boxWidth, boxHeight, 5);
      ctx.fillStyle = isDark ? 'rgba(9, 9, 11, 0.82)' : 'rgba(255, 255, 255, 0.9)';
      ctx.fill();
      ctx.strokeStyle = state.selected
        ? palette.rim
        : isDark
          ? 'rgba(255, 255, 255, 0.1)'
          : 'rgba(9, 9, 11, 0.08)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = palette.label;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, x, boxY + boxHeight / 2 + 0.5);
    }

    ctx.restore();
    return {
      nodeDimensions: {
        width: Math.max(size * 2 + 8, boxWidth),
        height: size * 2 + 27,
      },
    };
  };
}

function buildAdjacency(edges: GraphEdge[]): Map<string, Set<string>> {
  const adjacency = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
    adjacency.get(edge.source)!.add(edge.target);
    adjacency.get(edge.target)!.add(edge.source);
  }
  return adjacency;
}

function connectedComponent(start: string, adjacency: Map<string, Set<string>>): Set<string> {
  const seen = new Set<string>([start]);
  const queue = [start];
  while (queue.length) {
    const current = queue.shift()!;
    for (const next of adjacency.get(current) || []) {
      if (seen.has(next)) continue;
      seen.add(next);
      queue.push(next);
    }
  }
  return seen;
}

export default function KnowledgeGraph() {
  const { setActiveView, theme } = useApp();
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const nodesDataSetRef = useRef<DataSet<any> | null>(null);
  const edgesDataSetRef = useRef<DataSet<any> | null>(null);
  const baseNodesRef = useRef<Record<string, unknown>[]>([]);
  const baseEdgesRef = useRef<Record<string, unknown>[]>([]);
  const adjacencyRef = useRef<Map<string, Set<string>>>(new Map());

  const [stats, setStats] = useState('');
  const [showSections, setShowSections] = useState(false);
  const [search, setSearch] = useState('');
  const [data, setData] = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsRebuild, setNeedsRebuild] = useState(false);
  const [selection, setSelection] = useState<SelectionInfo | null>(null);

  const isDark = theme === 'dark';

  // Filter nodes: search box, sections toggle, entity cap (by degree).
  const filtered = useMemo(() => {
    if (data.nodes.length === 0) return data;

    const nodes = [...data.nodes];
    const edges = [...data.edges];

    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) || 0) + 1);
      degree.set(e.target, (degree.get(e.target) || 0) + 1);
    }

    // Cap entities by degree (most-connected survive) in every view.
    const entityNodes = nodes
      .filter(n => n.type === 'entity')
      .sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0));
    const keptEntityIds = new Set(
      entityNodes.slice(0, MAX_ENTITIES).map(n => n.id),
    );

    const byId = new Map(
      nodes
        .filter(n => showSections || n.type !== 'section')
        .filter(n => n.type !== 'entity' || keptEntityIds.has(n.id))
        .map(n => [n.id, n]),
    );
    const keptEdges = edges.filter(e => byId.has(e.source) && byId.has(e.target));
    return { nodes: [...byId.values()], edges: keptEdges };
  }, [data, showSections]);

  // Search: highlight matching nodes, keep their immediate neighbors visible.
  const searchFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return filtered;

    const ids = new Set<string>();
    const neighbors = new Set<string>();
    const outgoing = new Map<string, GraphEdge[]>();
    const incoming = new Map<string, GraphEdge[]>();
    for (const e of filtered.edges) {
      if (!outgoing.has(e.source)) outgoing.set(e.source, []);
      outgoing.get(e.source)!.push(e);
      if (!incoming.has(e.target)) incoming.set(e.target, []);
      incoming.get(e.target)!.push(e);
    }
    for (const n of filtered.nodes) {
      if (!n.label.toLowerCase().includes(q)) continue;
      ids.add(n.id);
      for (const e of outgoing.get(n.id) || []) neighbors.add(e.target);
      for (const e of incoming.get(n.id) || []) neighbors.add(e.source);
    }
    const visible = new Set([...ids, ...neighbors]);
    const nodes = filtered.nodes.filter(n => visible.has(n.id));
    const edges = filtered.edges.filter(e => visible.has(e.source) && visible.has(e.target));
    return { nodes, edges };
  }, [filtered, search]);

  const resetHighlight = useCallback(() => {
    nodesDataSetRef.current?.update(baseNodesRef.current.map(n => ({ id: n.id, opacity: 1 })));
    edgesDataSetRef.current?.update(baseEdgesRef.current);
    networkRef.current?.unselectAll();
    networkRef.current?.redraw();
    setSelection(null);
  }, []);

  const highlightNode = useCallback(
    (nodeId: string) => {
      const nodesDS = nodesDataSetRef.current;
      const edgesDS = edgesDataSetRef.current;
      const network = networkRef.current;
      if (!nodesDS || !edgesDS || !network) return;

      const node = searchFiltered.nodes.find(n => n.id === nodeId);
      if (!node) return;

      const adjacency = adjacencyRef.current;
      const component = connectedComponent(nodeId, adjacency);
      const connectedEdges = new Set<string>();

      nodesDS.update(
        baseNodesRef.current.map(n => ({
          id: n.id,
          opacity: component.has(String(n.id)) ? 1 : 0.1,
        })),
      );

      const highlightEdgeColor = isDark ? '#5eead4' : '#0f766e';
      const highlightFont = isDark ? '#ccfbf1' : '#115e59';
      const dimFont = isDark ? 'rgba(161, 161, 170, 0.14)' : 'rgba(82, 82, 91, 0.12)';

      edgesDS.update(
        baseEdgesRef.current.map(edge => {
          const from = String(edge.from);
          const to = String(edge.to);
          const connected = component.has(from) && component.has(to);
          if (connected) connectedEdges.add(String(edge.id));
          const baseColor = (edge.color || {}) as Record<string, unknown>;
          const baseFont = (edge.font || {}) as Record<string, unknown>;
          return {
            id: edge.id,
            width: connected ? 2.4 : 0.8,
            color: {
              ...baseColor,
              color: connected ? highlightEdgeColor : baseColor.color,
              opacity: connected ? 1 : 0.05,
            },
            font: {
              ...baseFont,
              color: connected ? highlightFont : dimFont,
              strokeWidth: connected ? 3 : 0,
            },
          };
        }),
      );

      network.selectNodes([nodeId]);
      network.redraw();

      setSelection({
        id: node.id,
        label: node.label,
        type: node.type,
        file_path: node.file_path,
        direct: adjacency.get(nodeId)?.size || 0,
        total: Math.max(0, component.size - 1),
      });

      // Frame the connected component so every attached node is readable.
      if (component.size < searchFiltered.nodes.length) {
        network.fit({
          nodes: [...component],
          animation: { duration: 420, easingFunction: 'easeInOutQuad' },
        });
      }
    },
    [searchFiltered.nodes, isDark],
  );

  useEffect(() => {
    if (!containerRef.current) return;

    if (loading) return;

    if (data.nodes.length === 0 || searchFiltered.nodes.length === 0) {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
      nodesDataSetRef.current = null;
      edgesDataSetRef.current = null;
      if (containerRef.current) containerRef.current.innerHTML = '';
      return;
    }

    const container = containerRef.current;
    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }
    container.innerHTML = '';

    const degree = new Map<string, number>();
    for (const edge of searchFiltered.edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    }

    const background = isDark ? '#09090b' : '#ffffff';
    const baseEdgeColor = isDark ? 'rgba(161, 161, 170, 0.36)' : 'rgba(82, 82, 91, 0.34)';
    const hoverEdgeColor = isDark ? '#5eead4' : '#0f766e';
    const edgeFontColor = isDark ? '#a1a1aa' : '#52525b';

    const visNodes = searchFiltered.nodes.map(n => {
      const kind = kindOf(n.type);
      const degreeCount = degree.get(n.id) || 0;
      const baseSize = kind === 'file' ? 19 : kind === 'entity' ? 15 : 11;
      const size = Math.min(baseSize + Math.sqrt(degreeCount) * 2.8, baseSize + 11);
      return {
        id: n.id,
        label: truncate(n.label, 30),
        title: `${n.label} (${TYPE_LABEL[n.type] || n.type})${n.file_path ? `\n${n.file_path}` : ''}\n${degreeCount} connection${degreeCount === 1 ? '' : 's'}\nClick to isolate its connections.`,
        shape: 'custom',
        size,
        opacity: 1,
        ctxRenderer: sphereRenderer(kind, isDark),
      };
    });

    const visEdges = searchFiltered.edges.map(e => ({
      id: `${e.source}->${e.target}`,
      from: e.source,
      to: e.target,
      label: e.relation,
      color: {
        color: baseEdgeColor,
        hover: hoverEdgeColor,
        highlight: hoverEdgeColor,
        opacity: 1,
        inherit: false,
      },
      font: {
        size: 9,
        color: edgeFontColor,
        strokeWidth: 3,
        strokeColor: background,
        face: 'Inter, sans-serif',
      },
      width: 1.2,
      hoverWidth: 1.8,
      selectionWidth: 2.4,
      smooth: { enabled: true, type: 'continuous' as const, roundness: 0.35 },
      arrows: { to: { enabled: true, scaleFactor: 0.55 } },
    }));

    baseNodesRef.current = visNodes as Record<string, unknown>[];
    baseEdgesRef.current = visEdges as Record<string, unknown>[];
    adjacencyRef.current = buildAdjacency(searchFiltered.edges);

    const nodesDS = new DataSet(visNodes);
    const edgesDS = new DataSet(visEdges);
    nodesDataSetRef.current = nodesDS;
    edgesDataSetRef.current = edgesDS;

    const network = new Network(
      container,
      { nodes: nodesDS, edges: edgesDS },
      {
        physics: {
          solver: 'forceAtlas2Based' as const,
          forceAtlas2Based: {
            gravitationalConstant: -85,
            centralGravity: 0.008,
            springLength: 210,
            springConstant: 0.018,
            damping: 0.45,
          },
          stabilization: { iterations: 220, updateInterval: 25 },
        },
        layout: { improvedLayout: true },
        interaction: {
          hover: true,
          tooltipDelay: 220,
          navigationButtons: true,
          keyboard: true,
          multiselect: false,
          selectConnectedEdges: false,
        },
        edges: { smooth: { enabled: true, type: 'continuous' as const, roundness: 0.35 } },
        nodes: { margin: { top: 8, right: 8, bottom: 8, left: 8 } },
      },
    );
    networkRef.current = network;

    network.on('click', params => {
      const nodeId = params.nodes?.[0] as string | undefined;
      if (!nodeId) {
        resetHighlight();
        return;
      }
      highlightNode(nodeId);
    });

    network.on('doubleClick', params => {
      const nodeId = params.nodes?.[0] as string | undefined;
      if (!nodeId) return;
      const component = connectedComponent(nodeId, adjacencyRef.current);
      network.fit({
        nodes: [...component],
        animation: { duration: 420, easingFunction: 'easeInOutQuad' },
      });
    });

    network.once('stabilizationIterationsDone', () => {
      // Freeze the layout once settled: it is easier to read and much cheaper.
      network.setOptions({ physics: { enabled: false } });
      network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    });

    setSelection(null);
  }, [data.nodes.length, highlightNode, isDark, loading, resetHighlight, searchFiltered]);

  const destroyNetwork = useCallback(() => {
    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }
    nodesDataSetRef.current = null;
    edgesDataSetRef.current = null;
    if (containerRef.current) containerRef.current.innerHTML = '';
    setSelection(null);
  }, []);

  const close = useCallback(() => {
    destroyNetwork();
    const modal = document.getElementById('graph-modal');
    if (modal) modal.style.display = 'none';
  }, [destroyNetwork]);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNeedsRebuild(false);
    try {
      const res = await api.graph.get();
      if (res.error) {
        setError(res.error);
        setData({ nodes: [], edges: [] });
        return;
      }
      const nodes = res.nodes || [];
      const edges = res.edges || [];
      setData({ nodes, edges });
      setStats(`${nodes.length} nodes · ${edges.length} edges`);
      setNeedsRebuild(Boolean(res.needs_rebuild));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'unknown error');
      setData({ nodes: [], edges: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const openHandler = () => {
      void loadGraph();
    };
    window.addEventListener('palimind:open-graph', openHandler);
    return () => window.removeEventListener('palimind:open-graph', openHandler);
  }, [loadGraph]);

  useEffect(() => {
    const modal = document.getElementById('graph-modal');
    if (!modal) return;
    const handler = (e: MouseEvent) => {
      if (e.target === modal) close();
    };
    modal.addEventListener('click', handler);
    return () => modal.removeEventListener('click', handler);
  }, [close]);

  useEffect(() => () => destroyNetwork(), [destroyNetwork]);

  const handleRebuild = async () => {
    try {
      const result = await api.graph.rebuild();
      if (result.error) {
        alert('Rebuild error: ' + result.error);
      } else {
        await loadGraph();
      }
    } catch (e) {
      console.error('Graph rebuild error:', e);
    }
  };

  const openSelectedFile = () => {
    setActiveView('fields');
    close();
  };

  const hasGraph = data.nodes.length > 0;
  const noMatches = hasGraph && searchFiltered.nodes.length === 0;

  return (
    <div id="graph-modal" className="modal" role="dialog" aria-modal="true" aria-labelledby="graph-title" style={{ display: 'none' }}>
      <div className="modal-content graph-modal-content">
        <div className="modal-header graph-modal-header">
          <h2 id="graph-title">Document Knowledge Graph</h2>
          <div className="graph-toolbar">
            <input
              type="text"
              className="graph-search"
              placeholder="Search nodes..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <label className="graph-toggle">
              <input type="checkbox" checked={showSections} onChange={e => setShowSections(e.target.checked)} />
              Sections
            </label>
            <span className="graph-stats">{stats}</span>
            <button className="action-btn graph-rebuild" title="Rebuild graph" onClick={handleRebuild}>
              Rebuild
            </button>
            <button className="icon-btn" title="Close Graph" aria-label="Close graph" onClick={close}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>
        <div className="modal-body graph-modal-body">
          <div className="graph-canvas-wrap">
            <div id="graph-visualization" ref={containerRef} />

            {loading && (
              <div className="graph-overlay">
                <span className="graph-loader" aria-hidden="true" />
                Loading knowledge graph…
              </div>
            )}

            {!loading && error && (
              <div className="graph-overlay graph-overlay--error">
                <strong>Could not load the graph</strong>
                <span>{error}</span>
                <button type="button" className="graph-overlay-btn" onClick={() => void loadGraph()}>
                  Retry
                </button>
              </div>
            )}

            {!loading && !error && !hasGraph && (
              <div className="graph-overlay">
                {needsRebuild
                  ? 'Graph not built yet — click Rebuild (this can take a moment).'
                  : 'No graph data. Sync your knowledge base first.'}
              </div>
            )}

            {!loading && !error && noMatches && (
              <div className="graph-overlay">No matching nodes.</div>
            )}

            {!loading && !error && hasGraph && !noMatches && !selection && (
              <div className="graph-hint">Click a node to isolate everything attached to it.</div>
            )}

            {!loading && !error && hasGraph && !noMatches && (
              <div className="graph-legend" aria-hidden="true">
                <span><i className="graph-legend-dot graph-legend-dot--file" />Files</span>
                <span><i className="graph-legend-dot graph-legend-dot--entity" />Entities</span>
                <span><i className="graph-legend-dot graph-legend-dot--section" />Sections</span>
              </div>
            )}

            {selection && (
              <div className="graph-selection-card" role="status">
                <div className="graph-selection-head">
                  <span className={`graph-selection-dot graph-selection-dot--${kindOf(selection.type)}`} />
                  <span className="graph-selection-title" title={selection.label}>{selection.label}</span>
                </div>
                <div className="graph-selection-meta">
                  {TYPE_LABEL[selection.type] || selection.type} · {selection.direct} direct connection
                  {selection.direct === 1 ? '' : 's'} · {selection.total} attached node
                  {selection.total === 1 ? '' : 's'}
                </div>
                {selection.file_path && (
                  <div className="graph-selection-path" title={selection.file_path}>{selection.file_path}</div>
                )}
                <div className="graph-selection-actions">
                  {selection.type === 'file' && (
                    <button type="button" className="graph-selection-btn" onClick={openSelectedFile}>
                      Open files view
                    </button>
                  )}
                  <button type="button" className="graph-selection-btn" onClick={resetHighlight}>
                    Clear
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
