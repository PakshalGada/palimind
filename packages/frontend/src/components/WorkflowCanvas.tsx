import { useRef, useState, useCallback, useEffect, forwardRef, useImperativeHandle } from 'react';
import type { Workflow, WorkflowNode, WorkflowNodeType } from '../types';
import { NODE_TYPE_ICONS } from './workflowNodeTypes';

interface WorkflowCanvasProps {
  workflow: Workflow;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  multiSelect: string[];
  connecting: { from: string; handle: string } | null;
  zoom: number;
  pan: { x: number; y: number };
  showGrid: boolean;
  gridSnap: boolean;
  minimapVisible: boolean;
  draggedNodeType: WorkflowNodeType | null;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
  onAddNode: (type: WorkflowNodeType, position: { x: number; y: number }) => void;
  onAddEdge: (source: string, target: string) => void;
  onDeleteNode: (id: string) => void;
  onDeleteEdge: (id: string) => void;
  onUpdateNodePosition: (id: string, pos: { x: number; y: number }) => void;
  onUpdateNodeName: (id: string, name: string) => void;
  onMultiSelect: (ids: string[]) => void;
  onConnectingChange: (c: { from: string; handle: string } | null) => void;
  onZoomChange: (z: number) => void;
  onPanChange: (p: { x: number; y: number }) => void;
  onDraggedNodeTypeConsumed: () => void;
}

const GRID_SIZE = 20;
const NODE_W = 180;
const NODE_H = 60;

const WorkflowCanvas = forwardRef<HTMLDivElement, WorkflowCanvasProps>((props, ref) => {
  const {
    workflow, selectedNodeId, selectedEdgeId, multiSelect, connecting,
    zoom, pan, showGrid, gridSnap, minimapVisible, draggedNodeType,
    onSelectNode, onSelectEdge, onAddNode, onAddEdge, onDeleteNode, onDeleteEdge,
    onUpdateNodePosition, onUpdateNodeName, onMultiSelect, onConnectingChange,
    onZoomChange, onPanChange, onDraggedNodeTypeConsumed,
  } = props;

  const containerRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [dropPreview, setDropPreview] = useState<{ x: number; y: number } | null>(null);
  const panOrigin = useRef<{ x: number; y: number } | null>(null);

  useImperativeHandle(ref, () => containerRef.current!);

  const screenToWorld = useCallback((sx: number, sy: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: (sx - rect.left - pan.x) / zoom,
      y: (sy - rect.top - pan.y) / zoom,
    };
  }, [pan, zoom]);

  const snapToGrid = useCallback((val: number) => {
    if (!gridSnap) return val;
    return Math.round(val / GRID_SIZE) * GRID_SIZE;
  }, [gridSnap]);

  // Mouse handlers for panning (middle mouse or Alt+drag on empty canvas).
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.target === containerRef.current || (e.target as HTMLElement).classList.contains('wf-canvas-inner')) {
      onSelectNode(null);
      onSelectEdge(null);
      onMultiSelect([]);
      if (e.button === 1 || (e.button === 0 && e.altKey)) {
        e.preventDefault();
        panOrigin.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
      }
    }
  }, [onSelectNode, onSelectEdge, onMultiSelect, pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (panOrigin.current) {
      onPanChange({ x: e.clientX - panOrigin.current.x, y: e.clientY - panOrigin.current.y });
      return;
    }
    if (dragging) {
      const world = screenToWorld(e.clientX, e.clientY);
      const newPos = {
        x: snapToGrid(world.x - dragging.offsetX),
        y: snapToGrid(world.y - dragging.offsetY),
      };
      onUpdateNodePosition(dragging.id, newPos);
    }
  }, [dragging, screenToWorld, snapToGrid, onUpdateNodePosition, onPanChange]);

  const handleMouseUp = useCallback(() => {
    setDragging(null);
    panOrigin.current = null;
  }, []);

  // Wheel zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    const newZoom = Math.max(0.25, Math.min(3, zoom + delta));
    onZoomChange(newZoom);
  }, [zoom, onZoomChange]);

  // Drag from palette
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const world = screenToWorld(e.clientX, e.clientY);
    setDropPreview({ x: snapToGrid(world.x - NODE_W / 2), y: snapToGrid(world.y - NODE_H / 2) });
  }, [screenToWorld, snapToGrid]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDropPreview(null);
    if (draggedNodeType) {
      const world = screenToWorld(e.clientX, e.clientY);
      onAddNode(draggedNodeType, {
        x: snapToGrid(world.x - NODE_W / 2),
        y: snapToGrid(world.y - NODE_H / 2),
      });
      onDraggedNodeTypeConsumed();
    }
  }, [draggedNodeType, screenToWorld, snapToGrid, onAddNode, onDraggedNodeTypeConsumed]);

  const handleDragLeave = useCallback(() => {
    setDropPreview(null);
  }, []);

  // Node mouse down - start drag
  const handleNodeMouseDown = useCallback((e: React.MouseEvent, node: WorkflowNode) => {
    e.stopPropagation();
    if (e.button !== 0) return;

    // Multi-select with shift
    if (e.shiftKey) {
      const isSelected = multiSelect.includes(node.id);
      onMultiSelect(isSelected
        ? multiSelect.filter(id => id !== node.id)
        : [...multiSelect, node.id]
      );
    } else if (!multiSelect.includes(node.id)) {
      onMultiSelect([node.id]);
    }

    onSelectNode(node.id);
    onSelectEdge(null);

    const world = screenToWorld(e.clientX, e.clientY);
    setDragging({
      id: node.id,
      offsetX: world.x - node.position.x,
      offsetY: world.y - node.position.y,
    });
  }, [multiSelect, onMultiSelect, onSelectNode, onSelectEdge, screenToWorld]);

  // Handle click for connecting
  const handleHandleClick = useCallback((e: React.MouseEvent, nodeId: string, handle: string, isSource: boolean) => {
    e.stopPropagation();
    if (isSource) {
      onConnectingChange({ from: nodeId, handle });
    } else if (connecting && connecting.from !== nodeId) {
      onAddEdge(connecting.from, nodeId);
      onConnectingChange(null);
    }
  }, [connecting, onConnectingChange, onAddEdge]);

  // Edge click
  const handleEdgeClick = useCallback((e: React.MouseEvent, edgeId: string) => {
    e.stopPropagation();
    onSelectEdge(edgeId);
    onSelectNode(null);
  }, [onSelectEdge, onSelectNode]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!containerRef.current?.contains(document.activeElement) && document.activeElement?.tagName !== 'INPUT') return;
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedNodeId && document.activeElement?.tagName !== 'INPUT') {
          e.preventDefault();
          onDeleteNode(selectedNodeId);
        }
        if (selectedEdgeId) {
          e.preventDefault();
          onDeleteEdge(selectedEdgeId);
        }
      }
      if (e.key === 'Escape') {
        onSelectNode(null);
        onSelectEdge(null);
        onConnectingChange(null);
        setEditingNodeId(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedNodeId, selectedEdgeId, onDeleteNode, onDeleteEdge, onSelectNode, onSelectEdge, onConnectingChange]);

  // Render edges as SVG
  const renderEdges = () => {
    return workflow.edges.map(edge => {
      const sourceNode = workflow.nodes.find(n => n.id === edge.source);
      const targetNode = workflow.nodes.find(n => n.id === edge.target);
      if (!sourceNode || !targetNode) return null;

      const sx = sourceNode.position.x + NODE_W;
      const sy = sourceNode.position.y + NODE_H / 2;
      const tx = targetNode.position.x;
      const ty = targetNode.position.y + NODE_H / 2;

      const dx = Math.abs(tx - sx);
      const cp = Math.max(50, dx / 2);

      const path = `M ${sx} ${sy} C ${sx + cp} ${sy}, ${tx - cp} ${ty}, ${tx} ${ty}`;
      const isSelected = selectedEdgeId === edge.id;

      return (
        <g key={edge.id}>
          <path
            d={path}
            fill="none"
            stroke="transparent"
            strokeWidth={12}
            className="wf-edge-hitarea"
            onClick={(e) => handleEdgeClick(e, edge.id)}
          />
          <path
            d={path}
            fill="none"
            strokeWidth={isSelected ? 3 : 2}
            className={isSelected ? 'wf-edge wf-edge--selected' : 'wf-edge'}
            markerEnd="url(#arrowhead)"
          />
          {edge.label && (
            <text
              x={(sx + tx) / 2}
              y={(sy + ty) / 2 - 8}
              textAnchor="middle"
              className="wf-edge-label"
            >
              {edge.label}
            </text>
          )}
        </g>
      );
    });
  };

  // Render connection line while connecting
  const renderConnectingLine = () => {
    if (!connecting) return null;
    const sourceNode = workflow.nodes.find(n => n.id === connecting.from);
    if (!sourceNode) return null;
    const sx = sourceNode.position.x + NODE_W;
    const sy = sourceNode.position.y + NODE_H / 2;
    return (
      <line
        x1={sx} y1={sy}
        x2={sx + 100} y2={sy}
        strokeWidth={2}
        strokeDasharray="5,5"
        className="wf-connecting-line"
      />
    );
  };

  // Minimap
  const renderMinimap = () => {
    if (!minimapVisible) return null;
    const mmW = 200;
    const mmH = 150;
    const allX = workflow.nodes.map(n => n.position.x);
    const allY = workflow.nodes.map(n => n.position.y);
    const minX = Math.min(...allX, 0) - 100;
    const minY = Math.min(...allY, 0) - 100;
    const maxX = Math.max(...allX, 0) + NODE_W + 100;
    const maxY = Math.max(...allY, 0) + NODE_H + 100;
    const scaleX = mmW / (maxX - minX);
    const scaleY = mmH / (maxY - minY);
    const scale = Math.min(scaleX, scaleY);

    return (
      <div className="wf-minimap" style={{ width: mmW, height: mmH }}>
        <svg width={mmW} height={mmH}>
          {workflow.nodes.map(n => (
            <rect
              key={n.id}
              x={(n.position.x - minX) * scale}
              y={(n.position.y - minY) * scale}
              width={NODE_W * scale}
              height={NODE_H * scale}
              rx={2}
              className={`wf-mm-node is-${n.status} ${selectedNodeId === n.id ? 'selected' : ''}`}
              strokeWidth={1}
            />
          ))}
          {/* Viewport rect */}
          <rect
            x={(-pan.x / zoom - minX) * scale}
            y={(-pan.y / zoom - minY) * scale}
            width={(containerRef.current?.clientWidth || 800) / zoom * scale}
            height={(containerRef.current?.clientHeight || 600) / zoom * scale}
            fill="none"
            className="wf-mm-viewport"
            strokeWidth={1}
            opacity={0.5}
          />
        </svg>
      </div>
    );
  };

  return (
    <div
      ref={containerRef}
      className="wf-canvas-container"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      onDragLeave={handleDragLeave}
    >
      <div
        className="wf-canvas-inner"
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: '0 0',
        }}
      >
        {/* Grid */}
        {showGrid && (
          <svg className="wf-grid" width="100%" height="100%">
            <defs>
              <pattern id="grid" width={GRID_SIZE} height={GRID_SIZE} patternUnits="userSpaceOnUse">
                <circle cx={GRID_SIZE} cy={GRID_SIZE} r={1} className="wf-grid-dot" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
        )}

        {/* Edges SVG */}
        <svg className="wf-edges-svg" width="100%" height="100%">
          <defs>
            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
              <polygon points="0 0, 10 3.5, 0 7" className="wf-arrowhead" />
            </marker>
          </defs>
          {renderEdges()}
          {renderConnectingLine()}
        </svg>

        {/* Drop preview */}
        {dropPreview && draggedNodeType && (
          <div
            className="wf-drop-preview"
            style={{
              left: dropPreview.x,
              top: dropPreview.y,
              width: NODE_W,
              height: NODE_H,
            }}
          />
        )}

        {/* Nodes */}
        {workflow.nodes.map(node => {
          const isSelected = selectedNodeId === node.id || multiSelect.includes(node.id);
          const statusClass = node.status === 'running' ? 'running' : node.status === 'done' ? 'done' : node.status === 'error' ? 'error' : '';
          return (
            <div
              key={node.id}
              className={`wf-node ${isSelected ? 'selected' : ''} ${statusClass}`}
              style={{
                left: node.position.x,
                top: node.position.y,
                width: NODE_W,
              }}
              onMouseDown={(e) => handleNodeMouseDown(e, node)}
            >
              {/* Connection handles */}
              <div
                className="wf-handle wf-handle-input"
                onClick={(e) => handleHandleClick(e, node.id, 'input', false)}
              />
              <div
                className="wf-handle wf-handle-output"
                onClick={(e) => handleHandleClick(e, node.id, 'output', true)}
              />

              <div className="wf-node-header">
                <NodeTypeIcon type={node.type} />
                {editingNodeId === node.id ? (
                  <input
                    className="wf-node-name-edit"
                    value={editName}
                    onChange={e => setEditName(e.target.value)}
                    onBlur={() => {
                      if (editName.trim()) onUpdateNodeName(node.id, editName.trim());
                      setEditingNodeId(null);
                    }}
                    onKeyDown={e => {
                      if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                      if (e.key === 'Escape') setEditingNodeId(null);
                    }}
                    autoFocus
                    onClick={e => e.stopPropagation()}
                  />
                ) : (
                  <span
                    className="wf-node-name"
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      setEditingNodeId(node.id);
                      setEditName(node.name);
                    }}
                  >
                    {node.name}
                  </span>
                )}
              </div>
              <div className="wf-node-type">{node.type}</div>
              {node.status === 'running' && <div className="wf-node-spinner" />}
              {node.status === 'error' && <div className="wf-node-error">{node.error}</div>}
            </div>
          );
        })}
      </div>

      {/* Minimap */}
      {renderMinimap()}
    </div>
  );
});

WorkflowCanvas.displayName = 'WorkflowCanvas';

function NodeTypeIcon({ type }: { type: WorkflowNodeType }) {
  const Icon = NODE_TYPE_ICONS[type];
  if (!Icon) return null;
  return <Icon size={14} className="wf-node-icon" />;
}

export default WorkflowCanvas;