import { useState, useCallback, useRef, useEffect } from 'react';
import {
  Play,
  Save,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Copy,
  Clipboard,
  LayoutTemplate,
  Grid3x3,
  Magnet,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api';
import { Button, Badge, Modal } from '../ui/primitives';
import type {
  Workflow,
  WorkflowNode,
  WorkflowEdge,
  WorkflowNodeType,
  WorkflowExecution,
  WorkflowTemplate,
} from '../types';
import { NODE_TYPE_CATEGORIES, NODE_TYPE_MAP } from './workflowNodeTypes';
import WorkflowCanvas from './WorkflowCanvas';
import NodePalette from './NodePalette';
import NodeConfigPanel from './NodeConfigPanel';
import WorkflowExecutionPanel from './WorkflowExecutionPanel';
import './WorkflowBuilder.css';

let nodeIdCounter = 0;
function genId(): string {
  return `node_${Date.now()}_${++nodeIdCounter}`;
}

const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'tpl_research',
    name: 'Research Pipeline',
    description: 'Search, summarize, output',
    category: 'Research',
    nodes: [
      { id: 'n1', type: 'webhook', name: 'Start', config: { path: '/research' }, position: { x: 100, y: 200 }, status: 'idle' },
      { id: 'n2', type: 'tool', name: 'Web Search', config: { tool: 'web_search', query: '{{input.query}}' }, position: { x: 350, y: 200 }, status: 'idle' },
      { id: 'n3', type: 'agent', name: 'Summarize', config: { prompt: 'Summarize: {{n2.output}}' }, position: { x: 600, y: 200 }, status: 'idle' },
      { id: 'n4', type: 'output', name: 'Save Report', config: { format: 'markdown' }, position: { x: 850, y: 200 }, status: 'idle' },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4' },
    ],
  },
  {
    id: 'tpl_approval',
    name: 'Approval Workflow',
    description: 'Task, approve, execute',
    category: 'Automation',
    nodes: [
      { id: 'n1', type: 'cron', name: 'Daily Check', config: { schedule: '0 9 * * *' }, position: { x: 100, y: 200 }, status: 'idle' },
      { id: 'n2', type: 'agent', name: 'Analyze', config: { prompt: 'Check system health' }, position: { x: 350, y: 200 }, status: 'idle' },
      { id: 'n3', type: 'condition', name: 'Needs Approval?', config: { condition: '{{n2.output.urgent}}' }, position: { x: 600, y: 200 }, status: 'idle' },
      { id: 'n4', type: 'output', name: 'Notify', config: { channel: 'email' }, position: { x: 850, y: 100 }, status: 'idle' },
      { id: 'n5', type: 'agent', name: 'Auto-Fix', config: { prompt: 'Fix issues' }, position: { x: 850, y: 300 }, status: 'idle' },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4', condition: 'true' },
      { id: 'e4', source: 'n3', target: 'n5', condition: 'false' },
    ],
  },
  {
    id: 'tpl_data',
    name: 'Data Processing',
    description: 'Fetch, transform, store',
    category: 'Data',
    nodes: [
      { id: 'n1', type: 'webhook', name: 'API Trigger', config: { path: '/data' }, position: { x: 100, y: 200 }, status: 'idle' },
      { id: 'n2', type: 'tool', name: 'Fetch Data', config: { tool: 'fetch_url' }, position: { x: 350, y: 200 }, status: 'idle' },
      { id: 'n3', type: 'transform', name: 'Parse JSON', config: { operation: 'json_parse' }, position: { x: 600, y: 200 }, status: 'idle' },
      { id: 'n4', type: 'code', name: 'Validate', config: { language: 'python', code: 'def validate(data):\n    return True' }, position: { x: 850, y: 200 }, status: 'idle' },
      { id: 'n5', type: 'output', name: 'Store', config: { destination: 'file' }, position: { x: 1100, y: 200 }, status: 'idle' },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4' },
      { id: 'e4', source: 'n4', target: 'n5' },
    ],
  },
];

function createEmptyWorkflow(): Workflow {
  return {
    id: `wf_${Date.now()}`,
    name: 'Untitled Workflow',
    description: '',
    nodes: [],
    edges: [],
    created_at: Date.now(),
    updated_at: Date.now(),
    status: 'draft',
    version: 1,
  };
}

export default function WorkflowBuilder() {
  const { addToast } = useApp();
  const [workflow, setWorkflow] = useState<Workflow>(createEmptyWorkflow);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [execution, setExecution] = useState<WorkflowExecution | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [showExecution, setShowExecution] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [connecting, setConnecting] = useState<{ from: string; handle: string } | null>(null);
  const [multiSelect, setMultiSelect] = useState<string[]>([]);
  const [history, setHistory] = useState<Workflow[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [clipboard, setClipboard] = useState<WorkflowNode[]>([]);
  const [draggedNodeType, setDraggedNodeType] = useState<WorkflowNodeType | null>(null);
  const [gridSnap, setGridSnap] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [minimapVisible, setMinimapVisible] = useState(true);
  const [workflowList, setWorkflowList] = useState<Workflow[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);

  const canvasRef = useRef<HTMLDivElement>(null);

  const loadWorkflows = useCallback(async () => {
    try {
      const data = await api.workflows.list();
      const list = data.workflows || [];
      setWorkflowList(list);
      if (list.length > 0) {
        setWorkflow(list[0]);
      }
    } catch {
      // No workflows yet — start fresh.
    }
  }, []);

  useEffect(() => {
    void loadWorkflows();
    api.agents
      .list()
      .then((d) => setAgents((d.agents || []).map((a) => ({ id: a.id, name: a.name }))))
      .catch(() => {});
  }, [loadWorkflows]);

  const pushHistory = useCallback((wf: Workflow) => {
    setHistory((prev) => {
      const next = prev.slice(0, historyIndex + 1);
      next.push(JSON.parse(JSON.stringify(wf)));
      if (next.length > 50) next.shift();
      return next;
    });
    setHistoryIndex((prev) => Math.min(prev + 1, 49));
  }, [historyIndex]);

  const saveWorkflow = useCallback(async () => {
    try {
      const updated = { ...workflow, updated_at: Date.now(), version: workflow.version + 1 };
      await api.workflows.save(updated);
      setWorkflow(updated);
      setWorkflowList((prev) => {
        const others = prev.filter((w) => w.id !== updated.id);
        return [...others, updated];
      });
      addToast('Workflow saved');
    } catch {
      addToast('Failed to save workflow');
    }
  }, [workflow, addToast]);

  const deleteNode = useCallback((nodeId: string) => {
    setWorkflow((prev) => {
      const next = {
        ...prev,
        nodes: prev.nodes.filter((n) => n.id !== nodeId),
        edges: prev.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
      };
      pushHistory(next);
      return next;
    });
    setSelectedNodeId((cur) => (cur === nodeId ? null : cur));
  }, [pushHistory]);

  const addNode = useCallback((type: WorkflowNodeType, position: { x: number; y: number }) => {
    const meta = NODE_TYPE_MAP[type];
    const newNode: WorkflowNode = {
      id: genId(),
      type,
      name: meta?.label || type,
      description: meta?.description || '',
      config: getDefaultConfig(type),
      position,
      status: 'idle',
    };
    setWorkflow((prev) => {
      const next = { ...prev, nodes: [...prev.nodes, newNode] };
      pushHistory(next);
      return next;
    });
    setSelectedNodeId(newNode.id);
    setSelectedEdgeId(null);
  }, [pushHistory]);

  const updateNodeConfig = useCallback((nodeId: string, config: Record<string, unknown>) => {
    setWorkflow((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) => (n.id === nodeId ? { ...n, config } : n)),
    }));
  }, []);

  const updateNodeName = useCallback((nodeId: string, name: string) => {
    setWorkflow((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) => (n.id === nodeId ? { ...n, name } : n)),
    }));
  }, []);

  const addEdge = useCallback((source: string, target: string) => {
    if (source === target) return;
    setWorkflow((prev) => {
      if (prev.edges.some((e) => e.source === source && e.target === target)) return prev;
      const newEdge: WorkflowEdge = {
        id: `edge_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        source,
        target,
      };
      const next = { ...prev, edges: [...prev.edges, newEdge] };
      pushHistory(next);
      return next;
    });
  }, [pushHistory]);

  const deleteEdge = useCallback((edgeId: string) => {
    setWorkflow((prev) => {
      const next = { ...prev, edges: prev.edges.filter((e) => e.id !== edgeId) };
      pushHistory(next);
      return next;
    });
    setSelectedEdgeId((cur) => (cur === edgeId ? null : cur));
  }, [pushHistory]);

  const undo = useCallback(() => {
    if (historyIndex < 0) return;
    const prev = history[historyIndex];
    if (prev) {
      setWorkflow(JSON.parse(JSON.stringify(prev)));
      setHistoryIndex((i) => i - 1);
    }
  }, [history, historyIndex]);

  const redo = useCallback(() => {
    if (historyIndex >= history.length - 1) return;
    const next = history[historyIndex + 2];
    if (next) {
      setWorkflow(JSON.parse(JSON.stringify(next)));
      setHistoryIndex((i) => i + 1);
    }
  }, [history, historyIndex]);

  const copyNodes = useCallback(() => {
    const selected = workflow.nodes.filter((n) => multiSelect.includes(n.id));
    if (selected.length > 0) {
      setClipboard(JSON.parse(JSON.stringify(selected)));
      addToast(`Copied ${selected.length} node(s)`);
    }
  }, [workflow.nodes, multiSelect, addToast]);

  const pasteNodes = useCallback(() => {
    if (clipboard.length === 0) return;
    const pasted = clipboard.map((n) => ({
      ...n,
      id: genId(),
      position: { x: n.position.x + 50, y: n.position.y + 50 },
    }));
    setWorkflow((prev) => {
      const next = { ...prev, nodes: [...prev.nodes, ...pasted] };
      pushHistory(next);
      return next;
    });
    setMultiSelect(pasted.map((n) => n.id));
    addToast(`Pasted ${pasted.length} node(s)`);
  }, [clipboard, addToast, pushHistory]);

  // Keyboard shortcuts scoped to the workflow surface.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (mod && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        redo();
      } else if (mod && e.key.toLowerCase() === 'c') {
        copyNodes();
      } else if (mod && e.key.toLowerCase() === 'v') {
        pasteNodes();
      } else if (mod && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void saveWorkflow();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [undo, redo, copyNodes, pasteNodes, saveWorkflow]);

  const runWorkflow = useCallback(async () => {
    if (workflow.nodes.length === 0) {
      addToast('Add some nodes first');
      return;
    }
    setShowExecution(true);
    setExecution({
      id: 'exec_pending',
      workflow_id: workflow.id,
      status: 'running',
      started_at: Date.now(),
      node_results: {},
      logs: [],
    });
    setWorkflow((prev) => ({ ...prev, nodes: prev.nodes.map((n) => ({ ...n, status: 'pending' })) }));

    try {
      // Persist first so agent nodes resolve against the saved workflow.
      const saved = await api.workflows.save(workflow);
      const runId = saved && !saved.error && saved.id ? saved.id : workflow.id;
      const res = await api.workflows.run(runId);
      if (res.error || !res.execution) {
        addToast(res.error || 'Workflow run failed');
        setExecution(null);
        return;
      }
      const exec = res.execution;
      setExecution(exec);
      setWorkflow((prev) => ({
        ...prev,
        nodes: prev.nodes.map((n) => {
          const r = exec.node_results?.[n.id];
          if (!r) return { ...n, status: 'skipped' };
          return { ...n, status: r.status, error: r.error };
        }),
      }));
      addToast(exec.status === 'failed' ? 'Workflow finished with errors' : 'Workflow completed');
    } catch {
      addToast('Workflow run failed');
      setExecution(null);
    }
  }, [workflow, addToast]);

  const loadTemplate = useCallback((template: WorkflowTemplate) => {
    const idMap: Record<string, string> = {};
    const nodes = template.nodes.map((n) => {
      const newId = genId();
      idMap[n.id] = newId;
      return { ...n, id: newId, status: 'idle' as const };
    });
    const edges = template.edges.map((e) => ({
      ...e,
      id: `edge_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      source: idMap[e.source] || e.source,
      target: idMap[e.target] || e.target,
    }));
    setWorkflow({
      id: `wf_${Date.now()}`,
      name: template.name,
      description: template.description,
      nodes,
      edges,
      created_at: Date.now(),
      updated_at: Date.now(),
      status: 'draft',
      version: 1,
    });
    setHistory([]);
    setHistoryIndex(-1);
    setShowTemplates(false);
    addToast(`Loaded template: ${template.name}`);
  }, [addToast]);

  const newWorkflow = useCallback(() => {
    setWorkflow(createEmptyWorkflow());
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setExecution(null);
    setShowExecution(false);
    setHistory([]);
    setHistoryIndex(-1);
  }, []);

  const resetCanvas = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const selectedNode = workflow.nodes.find((n) => n.id === selectedNodeId) || null;

  return (
    <div className="wf-panel">
      <div className="wf-topbar">
        <div className="wf-topbar-left">
          <input
            className="wf-name-input"
            value={workflow.name}
            onChange={(e) => setWorkflow((prev) => ({ ...prev, name: e.target.value }))}
            placeholder="Workflow name"
          />
          <Badge tone={workflow.status === 'active' ? 'success' : 'default'}>{workflow.status}</Badge>
          <span className="wf-version">v{workflow.version}</span>
        </div>
        <div className="wf-topbar-center">
          <Button onClick={newWorkflow} title="New workflow">
            <LayoutTemplate size={15} />
          </Button>
          <Button onClick={undo} disabled={historyIndex < 0} title="Undo (Ctrl+Z)">
            <Undo2 size={15} />
          </Button>
          <Button onClick={redo} disabled={historyIndex >= history.length - 1} title="Redo (Ctrl+Y)">
            <Redo2 size={15} />
          </Button>
          <div className="wf-divider" />
          <Button onClick={() => setShowTemplates(true)} title="Templates">
            <LayoutTemplate size={15} /> Templates
          </Button>
          <Button onClick={copyNodes} disabled={multiSelect.length === 0} title="Copy (Ctrl+C)">
            <Copy size={15} />
          </Button>
          <Button onClick={pasteNodes} disabled={clipboard.length === 0} title="Paste (Ctrl+V)">
            <Clipboard size={15} />
          </Button>
          <div className="wf-divider" />
          <Button onClick={() => setShowGrid((g) => !g)} variant={showGrid ? 'primary' : 'ghost'} title="Toggle grid">
            <Grid3x3 size={15} />
          </Button>
          <Button onClick={() => setGridSnap((s) => !s)} variant={gridSnap ? 'primary' : 'ghost'} title="Toggle snapping">
            <Magnet size={15} />
          </Button>
        </div>
        <div className="wf-topbar-right">
          <Button onClick={saveWorkflow} variant="primary">
            <Save size={15} /> Save
          </Button>
          <Button onClick={runWorkflow} variant="primary">
            <Play size={15} /> Run
          </Button>
        </div>
      </div>

      <div className="wf-main">
        <NodePalette
          categories={NODE_TYPE_CATEGORIES}
          onDragStart={setDraggedNodeType}
        />

        <div className="wf-canvas-area">
          <WorkflowCanvas
            ref={canvasRef}
            workflow={workflow}
            selectedNodeId={selectedNodeId}
            selectedEdgeId={selectedEdgeId}
            multiSelect={multiSelect}
            connecting={connecting}
            zoom={zoom}
            pan={pan}
            showGrid={showGrid}
            gridSnap={gridSnap}
            minimapVisible={minimapVisible}
            onSelectNode={setSelectedNodeId}
            onSelectEdge={setSelectedEdgeId}
            onAddNode={addNode}
            onAddEdge={addEdge}
            onDeleteNode={deleteNode}
            onDeleteEdge={deleteEdge}
            onUpdateNodePosition={(id, pos) => {
              setWorkflow((prev) => ({
                ...prev,
                nodes: prev.nodes.map((n) => (n.id === id ? { ...n, position: pos } : n)),
              }));
            }}
            onUpdateNodeName={updateNodeName}
            onMultiSelect={setMultiSelect}
            onConnectingChange={setConnecting}
            onZoomChange={setZoom}
            onPanChange={setPan}
            draggedNodeType={draggedNodeType}
            onDraggedNodeTypeConsumed={() => setDraggedNodeType(null)}
          />
          {workflow.nodes.length === 0 && (
            <div className="wf-canvas-hint">
              <Grid3x3 size={22} />
              <p>Drag a node from the palette onto the canvas to begin</p>
            </div>
          )}
          <div className="wf-zoom-controls">
            <button onClick={() => setZoom((z) => Math.max(0.25, z - 0.1))} aria-label="Zoom out">
              <ZoomOut size={15} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button onClick={() => setZoom((z) => Math.min(3, z + 0.1))} aria-label="Zoom in">
              <ZoomIn size={15} />
            </button>
            <button onClick={resetCanvas} aria-label="Reset view">
              <Maximize2 size={15} />
            </button>
            <button
              onClick={() => setMinimapVisible((v) => !v)}
              aria-label="Toggle minimap"
              className={minimapVisible ? 'active' : ''}
            >
              <Grid3x3 size={15} />
            </button>
          </div>
        </div>

        <NodeConfigPanel
          node={selectedNode}
          workflow={workflow}
          agents={agents}
          onUpdateConfig={updateNodeConfig}
          onUpdateName={updateNodeName}
          onDelete={deleteNode}
          onClose={() => setSelectedNodeId(null)}
        />
      </div>

      {showExecution && execution && (
        <WorkflowExecutionPanel
          execution={execution}
          workflow={workflow}
          onClose={() => {
            setShowExecution(false);
            setExecution(null);
          }}
        />
      )}

      <Modal open={showTemplates} onClose={() => setShowTemplates(false)} title="Workflow Templates">
          <div className="wf-templates-grid">
            {WORKFLOW_TEMPLATES.map((tpl) => (
              <button key={tpl.id} className="wf-template-card" onClick={() => loadTemplate(tpl)}>
                <LayoutTemplate size={20} className="wf-template-icon" />
                <div className="wf-template-name">{tpl.name}</div>
                <div className="wf-template-desc">{tpl.description}</div>
                <div className="wf-template-meta">
                  <Badge>{tpl.category}</Badge>
                  <span>{tpl.nodes.length} nodes</span>
                </div>
              </button>
            ))}
          </div>
        </Modal>

      {workflowList.length > 1 && (
        <div className="wf-saved-strip">
          <span className="wf-saved-label">Saved</span>
          {workflowList.map((wf) => (
            <button
              key={wf.id}
              className={`wf-saved-item ${wf.id === workflow.id ? 'active' : ''}`}
              onClick={() => setWorkflow(wf)}
            >
              {wf.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function getDefaultConfig(type: WorkflowNodeType): Record<string, unknown> {
  switch (type) {
    case 'agent':
      return { agent_id: '', prompt: '', model: '' };
    case 'tool':
      return { tool: 'web_search', args: {} };
    case 'condition':
      return { condition: '', true_branch: '', false_branch: '' };
    case 'loop':
      return { items: '', max_iterations: 10 };
    case 'delay':
      return { seconds: 5 };
    case 'webhook':
      return { path: '/webhook', method: 'POST' };
    case 'cron':
      return { schedule: '0 * * * *' };
    case 'code':
      return { language: 'python', code: '' };
    case 'transform':
      return { operation: 'json_parse', input: '' };
    case 'output':
      return { destination: 'file', format: 'json' };
    default:
      return {};
  }
}


