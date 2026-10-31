import { useState } from 'react';
import { ChevronDown, ChevronRight, File, Folder } from 'lucide-react';
import type { ArtifactFile } from '../../utils/artifacts';

interface TreeNode {
  name: string;
  path: string;
  isFile: boolean;
  children: TreeNode[];
}

function buildTree(files: ArtifactFile[]): TreeNode[] {
  const root: TreeNode[] = [];

  const sort = (nodes: TreeNode[]) => {
    nodes.sort(
      (a, b) => Number(a.isFile) - Number(b.isFile) || a.name.localeCompare(b.name),
    );
    for (const node of nodes) sort(node.children);
  };

  for (const file of files) {
    const parts = file.path.replace(/\\/g, '/').split('/').filter(Boolean);
    if (parts.length === 0) continue;
    let level = root;
    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      let node = level.find(item => item.name === part && item.isFile === isFile);
      if (!node) {
        node = {
          name: part,
          path: parts.slice(0, index + 1).join('/'),
          isFile,
          children: [],
        };
        level.push(node);
      }
      level = node.children;
    });
  }

  sort(root);
  return root;
}

function TreeBranch({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string;
  onSelect: (path: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const indent = 6 + depth * 12;

  if (node.isFile) {
    return (
      <button
        type="button"
        role="treeitem"
        aria-selected={node.path === selectedPath}
        className={`artifact-tree-row artifact-tree-file${
          node.path === selectedPath ? ' is-selected' : ''
        }`}
        style={{ paddingLeft: indent }}
        title={node.path}
        onClick={() => onSelect(node.path)}
      >
        <File size={12} className="artifact-tree-icon" />
        <span className="artifact-tree-name">{node.name}</span>
      </button>
    );
  }

  return (
    <div role="group">
      <button
        type="button"
        className="artifact-tree-row artifact-tree-folder"
        style={{ paddingLeft: indent }}
        onClick={() => setOpen(value => !value)}
        title={node.path}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Folder size={12} className="artifact-tree-icon" />
        <span className="artifact-tree-name">{node.name}</span>
      </button>
      {open &&
        node.children.map(child => (
          <TreeBranch
            key={`${child.path}:${child.isFile}`}
            node={child}
            depth={depth + 1}
            selectedPath={selectedPath}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

/** Collapsible file tree for multi-file artifacts. */
export default function ArtifactFileTree({
  files,
  selectedPath,
  onSelect,
}: {
  files: ArtifactFile[];
  selectedPath: string;
  onSelect: (path: string) => void;
}) {
  const tree = buildTree(files);
  return (
    <nav className="artifact-tree" role="tree" aria-label="Artifact files">
      {tree.map(node => (
        <TreeBranch
          key={`${node.path}:${node.isFile}`}
          node={node}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
        />
      ))}
    </nav>
  );
}
