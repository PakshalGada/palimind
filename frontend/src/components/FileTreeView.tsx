import { useState, useEffect, useCallback } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { TreeNode } from '../types';
import LoadingSpinner from './LoadingSpinner';

function TreeNodeComponent({ node, selectedFiles }: {
  node: TreeNode;
  selectedFiles: Set<string>;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const [children, setChildren] = useState<TreeNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const isDir = node.type === 'directory';

  const toggle = useCallback(async () => {
    if (!collapsed) {
      setCollapsed(true);
      return;
    }
    if (children === null) {
      setLoading(true);
      try {
        const data = await api.files.treeSub(node.path);
        if (!data.error) setChildren(data.children || []);
      } catch (e) {
        console.error('fetch subtree error:', e);
      }
      setLoading(false);
    }
    setCollapsed(false);
  }, [collapsed, children, node.path]);

  return (
    <div className="tree-node">
      <div className="tree-node-row">
        <span className="tree-chevron" style={{ visibility: isDir ? 'visible' : 'hidden' }}>
          {isDir && (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              onClick={toggle}
              style={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform 0.15s' }}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          )}
        </span>
        <span className="tree-icon-container">
          {isDir ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><polyline points="13 2 13 9 20 9" />
            </svg>
          )}
        </span>
        <span className="node-name" title={node.path}>{node.name}</span>
      </div>
      {isDir && !collapsed && (
        <div className="tree-node-children">
          {loading ? (
            <LoadingSpinner size="sm" text="Loading..." inline />
          ) : children?.length ? (
            children.map((child, i) => (
              <TreeNodeComponent key={i} node={child} selectedFiles={selectedFiles} />
            ))
          ) : (
            <div style={{ color: 'var(--text-muted)', padding: '4px 8px', fontSize: '0.78rem' }}>Empty</div>
          )}
        </div>
      )}
    </div>
  );
}

export default function FileTreeView({ modal }: { modal?: boolean }) {
  const { activeField, selectedFiles } = useApp();
  const [treeData, setTreeData] = useState<TreeNode[] | null>(null);

  const fetchTree = useCallback(async () => {
    if (!activeField) return;
    try {
      const data = await api.files.treeSub('');
      if (!data.error && data.children) {
        setTreeData(data.children);
      }
    } catch (e) {
      console.error('fetch file tree error:', e);
    }
  }, [activeField]);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  useEffect(() => {
    const handler = () => fetchTree();
    window.addEventListener('palimind:field-added', handler);
    return () => window.removeEventListener('palimind:field-added', handler);
  }, [fetchTree]);

  if (!activeField) return null;

  const renderTree = () => {
    if (treeData === null) {
      return <LoadingSpinner text="Loading folder structure..." />;
    }
    if (treeData.length === 0) {
      return <div style={{ color: 'var(--text-muted)', padding: 8 }}>Empty folder</div>;
    }
    return treeData.map((node, i) => (
      <TreeNodeComponent key={i} node={node} selectedFiles={selectedFiles} />
    ));
  };

  if (modal) {
    return (
      <div id="file-tree" className="file-tree">
        {renderTree()}
      </div>
    );
  }

  return (
    <div className="file-explorer-container">
      <div className="file-tree">
        {renderTree()}
      </div>
    </div>
  );
}