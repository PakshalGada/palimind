import { useEffect, useMemo, useRef, useState } from 'react';
import { DataSet } from 'vis-data';
import { Network } from 'vis-network';
import 'vis-network/styles/vis-network.css';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { GraphData } from '../types';

const MAX_ENTITIES = 40;

export default function KnowledgeGraph() {
  const { setActiveView } = useApp();
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [stats, setStats] = useState('');
  const [showSections, setShowSections] = useState(false);
  const [search, setSearch] = useState('');
  const [data, setData] = useState<GraphData>({ nodes: [], edges: [] });

  const close = () => {
    const modal = document.getElementById('graph-modal');
    if (modal) modal.style.display = 'none';
  };

  // Filter nodes: search box, sections toggle, entity cap (by degree).
  const filtered = useMemo(() => {
    if (data.nodes.length === 0) return data;

    const nodes = [...data.nodes];
    const edges = [...data.edges];

    // Hide sections unless toggled.
    const sectionIds = new Set(nodes.filter(n => n.type === 'section').map(n => n.id));
    if (!showSections) {
      const byId = new Map(nodes.filter(n => n.type !== 'section').map(n => [n.id, n]));
      const keptEdges = edges.filter(
        e => !sectionIds.has(e.source) && !sectionIds.has(e.target),
      );
      return { nodes: [...byId.values()], edges: keptEdges };
    }

    // Cap entities by degree (most-connected survive).
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) || 0) + 1);
      degree.set(e.target, (degree.get(e.target) || 0) + 1);
    }
    const entityNodes = nodes
      .filter(n => n.type === 'entity')
      .sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0));
    const keptEntityIds = new Set(
      entityNodes.slice(0, MAX_ENTITIES).map(n => n.id),
    );
    const byId = new Map(nodes.filter(n => n.type !== 'entity' || keptEntityIds.has(n.id)).map(n => [n.id, n]));
    const keptEdges = edges.filter(e => byId.has(e.source) && byId.has(e.target));
    return { nodes: [...byId.values()], edges: keptEdges };
  }, [data, showSections]);

  // Search: highlight matching nodes, keep their immediate neighbors visible.
  const searchFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return filtered;

    const ids = new Set<string>();
    const neighbors = new Set<string>();
    const edgeMap = new Map<string, { source: string; target: string }[]>();
    for (const e of filtered.edges) {
      const key = e.source;
      if (!edgeMap.has(key)) edgeMap.set(key, []);
      edgeMap.get(key)!.push(e);
    }
    for (const n of filtered.nodes) {
      if (n.label.toLowerCase().includes(q)) {
        ids.add(n.id);
        for (const e of edgeMap.get(n.id) || []) neighbors.add(e.target);
        for (const [src, es] of edgeMap) {
          for (const e of es) if (e.target === n.id) neighbors.add(src);
        }
      }
    }
    const visible = new Set([...ids, ...neighbors]);
    const nodes = filtered.nodes.filter(n => visible.has(n.id));
    const edges = filtered.edges.filter(e => visible.has(e.source) && visible.has(e.target));
    return { nodes, edges };
  }, [filtered, search]);

  const render = () => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    container.innerHTML = '';
    if (searchFiltered.nodes.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">No matching nodes.</div>';
      return;
    }

    const isDark = !document.documentElement.classList.contains('light-mode');

    const visNodes = searchFiltered.nodes.map(n => ({
      id: n.id,
      label: n.label.length > 25 ? n.label.substring(0, 22) + '...' : n.label,
      title: `${n.label} (${n.type})${n.file_path ? '\n' + n.file_path : ''}`,
      shape: n.type === 'file' ? 'box' : n.type === 'entity' ? 'ellipse' : 'diamond',
      color: n.type === 'file'
        ? (isDark ? { background: '#27272a', border: '#ffffff' } : { background: '#f4f4f5', border: '#09090b' })
        : n.type === 'entity'
        ? (isDark ? { background: '#18181b', border: '#a1a1aa' } : { background: '#ffffff', border: '#52525b' })
        : (isDark ? { background: '#09090b', border: '#71717a' } : { background: '#e4e4e7', border: '#27272a' }),
      font: { color: isDark ? '#ffffff' : '#09090b', size: 11, face: 'Inter, sans-serif' },
      borderWidth: 1.5,
      size: n.type === 'file' ? 22 : n.type === 'entity' ? 18 : 16,
    }));

    const visEdges = searchFiltered.edges.map(e => ({
      id: `${e.source}->${e.target}`,
      from: e.source,
      to: e.target,
      label: e.relation,
      font: { size: 9, color: isDark ? '#a1a1aa' : '#71717a', strokeWidth: 0, face: 'Inter, sans-serif' },
      color: { color: isDark ? '#3f3f46' : '#d4d4d8', hover: isDark ? '#ffffff' : '#000000' },
      width: 1,
      smooth: { enabled: true, type: 'curvedCW' as const, roundness: 0.1 },
      arrows: { to: { enabled: true, scaleFactor: 0.6 } },
    }));

    const network = new Network(
      container,
      { nodes: new DataSet(visNodes), edges: new DataSet(visEdges) },
      {
        physics: {
          solver: 'forceAtlas2Based' as const,
          forceAtlas2Based: {
            gravitationalConstant: -60,
            centralGravity: 0.005,
            springLength: 180,
            springConstant: 0.02,
            damping: 0.4,
          },
          stabilization: { iterations: 100 },
        },
        layout: { improvedLayout: true },
        interaction: {
          hover: true,
          tooltipDelay: 200,
          navigationButtons: true,
          keyboard: true,
        },
        edges: { smooth: { enabled: true, type: 'continuous' as const, roundness: 0.5 } },
        nodes: { margin: { top: 8, right: 8, bottom: 8, left: 8 } },
      },
    );
    networkRef.current = network;

    // Click a file node → open the Files (field) view.
    network.on('click', params => {
      if (!params.nodes || params.nodes.length === 0) return;
      const nodeId = params.nodes[0] as string;
      const node = searchFiltered.nodes.find(n => n.id === nodeId);
      if (node?.type === 'file') {
        setActiveView('fields');
        close();
      }
    });

    network.once('stabilizationIterationsDone', () => {
      network.fit({ animation: true });
    });
  };

  const loadGraph = async () => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;height:100%;color:var(--text-muted)"><div class="loading-spinner-container size-lg"><svg class="loading-spinner-svg" width="32" height="32" viewBox="0 0 24 24" fill="none"><circle class="loading-spinner-track" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2.5"/><path class="loading-spinner-head" d="M12 2C6.47715 2 2 6.47715 2 12C2 14.7364 3.09743 17.2166 4.87858 19.034" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div><span>Loading Knowledge Graph...</span></div>';

    try {
      const res: GraphData & { error?: string; needs_rebuild?: boolean } = await api.graph.get();
      if (res.error) {
        containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Graph error: ${res.error}</div>`;
        return;
      }
      const nodes = res.nodes || [];
      const edges = res.edges || [];
      setData({ nodes, edges });
      setStats(`${nodes.length} nodes · ${edges.length} edges`);

      if (nodes.length === 0) {
        containerRef.current.innerHTML = res.needs_rebuild
          ? '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Graph not built yet — click Rebuild (this can take a moment).</div>'
          : '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">No graph data. Sync your knowledge base first.</div>';
        return;
      }
      render();
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'unknown';
      if (containerRef.current) {
        containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Failed to load graph: ${msg}</div>`;
      }
    }
  };

  useEffect(() => {
    const openHandler = () => loadGraph();
    window.addEventListener('palimind:open-graph', openHandler);
    return () => window.removeEventListener('palimind:open-graph', openHandler);
  }, []);

  // Re-render when filters change.
  useEffect(() => {
    if (data.nodes.length > 0) render();
  }, [searchFiltered]);

  useEffect(() => {
    const modal = document.getElementById('graph-modal');
    if (!modal) return;
    const handler = (e: MouseEvent) => {
      if (e.target === modal) close();
    };
    modal.addEventListener('click', handler);
    return () => modal.removeEventListener('click', handler);
  }, []);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      const modal = document.getElementById('graph-modal');
      if (modal && modal.style.display === 'flex') loadGraph();
    });
    if (document.documentElement) {
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    }
    return () => observer.disconnect();
  }, []);

  const handleRebuild = async () => {
    try {
      const data2 = await api.graph.rebuild();
      if (data2.error) {
        alert('Rebuild error: ' + data2.error);
      } else {
        await loadGraph();
      }
    } catch (e) {
      console.error('Graph rebuild error:', e);
    }
  };

  return (
    <div id="graph-modal" className="modal" role="dialog" aria-modal="true" aria-labelledby="graph-title" style={{ display: 'none' }}>
      <div className="modal-content graph-modal-content">
        <div className="modal-header">
          <h2 id="graph-title">Document Knowledge Graph</h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Search nodes..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                padding: '5px 10px',
                background: 'var(--input-bg)',
                border: '1px solid var(--border-color)',
                borderRadius: 8,
                color: 'var(--text-main)',
                fontSize: '0.8rem',
                width: 160,
              }}
            />
            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
              <input type="checkbox" checked={showSections} onChange={e => setShowSections(e.target.checked)} />
              Sections
            </label>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{stats}</span>
            <button className="action-btn" title="Rebuild graph" onClick={handleRebuild}>
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
          <div
            id="graph-visualization"
            ref={containerRef}
            style={{ width: '100%', height: '100%', background: 'var(--bg-color)' }}
          />
        </div>
      </div>
    </div>
  );
}