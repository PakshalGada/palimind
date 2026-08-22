import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { GraphData } from '../types';

declare global {
  interface Window {
    vis: {
      Network: { new (...args: unknown[]): { fit: (opts: object) => void; once: (event: string, cb: () => void) => void } };
      DataSet: { new (...args: unknown[]): unknown };
    };
  }
}

export default function KnowledgeGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stats, setStats] = useState('');

  const close = () => {
    const modal = document.getElementById('graph-modal');
    if (modal) modal.style.display = 'none';
  };

  const loadGraph = async () => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;height:100%;color:var(--text-muted)"><div class="loading-spinner-container size-lg"><svg class="loading-spinner-svg" width="32" height="32" viewBox="0 0 24 24" fill="none"><circle class="loading-spinner-track" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2.5"/><path class="loading-spinner-head" d="M12 2C6.47715 2 2 6.47715 2 12C2 14.7364 3.09743 17.2166 4.87858 19.034" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div><span>Building Knowledge Graph...</span></div>';

    try {
      const data: GraphData & { error?: string } = await api.graph.get();
      if (data.error) {
        containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Graph error: ${data.error}</div>`;
        return;
      }

      const nodes = data.nodes || [];
      const edges = data.edges || [];
      setStats(`${nodes.length} nodes · ${edges.length} edges`);

      if (nodes.length === 0) {
        containerRef.current.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">No graph data. Sync your field first.</div>';
        return;
      }

      const vis = window.vis;
      if (!vis || !vis.Network) {
        containerRef.current.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">vis-network not loaded</div>';
        return;
      }

      const isDark = !document.documentElement.classList.contains('light-mode');

      const visNodes = nodes.map(n => ({
        id: n.id,
        label: n.label.length > 25 ? n.label.substring(0, 22) + '...' : n.label,
        title: `${n.label} (${n.type})${n.file_path ? '\n' + n.file_path : ''}`,
        shape: n.type === 'file' ? 'box' : (n.type === 'entity' ? 'ellipse' : 'diamond'),
        color: n.type === 'file'
          ? (isDark ? { background: '#27272a', border: '#ffffff' } : { background: '#f4f4f5', border: '#09090b' })
          : n.type === 'entity'
          ? (isDark ? { background: '#18181b', border: '#a1a1aa' } : { background: '#ffffff', border: '#52525b' })
          : (isDark ? { background: '#09090b', border: '#71717a' } : { background: '#e4e4e7', border: '#27272a' }),
        font: { color: isDark ? '#ffffff' : '#09090b', size: 11, face: 'Inter, sans-serif' },
        borderWidth: 1.5,
        size: n.type === 'file' ? 22 : (n.type === 'entity' ? 18 : 16),
      }));

      const visEdges = edges.map(e => ({
        from: e.source,
        to: e.target,
        label: e.relation,
        font: { size: 9, color: isDark ? '#a1a1aa' : '#71717a', strokeWidth: 0, face: 'Inter, sans-serif' },
        color: { color: isDark ? '#3f3f46' : '#d4d4d8', hover: isDark ? '#ffffff' : '#000000' },
        width: 1,
        smooth: { type: 'curvedCW', roundness: 0.1 },
        arrows: { to: { enabled: true, scaleFactor: 0.6 } },
      }));

      const options = {
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
        edges: { smooth: { type: 'continuous' as const } },
        nodes: { margin: 8 },
        background: isDark ? '#09090b' : '#ffffff',
      };

      containerRef.current.innerHTML = '';
      const datasetNodes = new vis.DataSet(visNodes);
      const datasetEdges = new vis.DataSet(visEdges);
      const network = new vis.Network(containerRef.current, { nodes: datasetNodes, edges: datasetEdges }, options);

      network.once('stabilizationIterationsDone', () => {
        network.fit({ animation: true });
      });
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
      const data = await api.graph.rebuild();
      if (data.error) {
        alert('Rebuild error: ' + data.error);
      } else {
        loadGraph();
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
            style={{
              width: '100%',
              height: '100%',
              background: 'var(--bg-color, #1a1a2e)',
            }}
          />
        </div>
      </div>
    </div>
  );
}
