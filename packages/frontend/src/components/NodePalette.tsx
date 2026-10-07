import { useState } from 'react';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import type { WorkflowNodeType } from '../types';
import type { WorkflowNodeTypeCategory } from './workflowNodeTypes';

interface NodePaletteProps {
  categories: WorkflowNodeTypeCategory[];
  onDragStart: (type: WorkflowNodeType) => void;
}

export default function NodePalette({ categories, onDragStart }: NodePaletteProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState('');
  const [expandedCats, setExpandedCats] = useState<Set<string>>(
    new Set(categories.map((c) => c.category)),
  );

  const toggleCat = (cat: string) => {
    setExpandedCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const filtered = categories
    .map((cat) => ({
      ...cat,
      types: cat.types.filter(
        (t) =>
          t.label.toLowerCase().includes(search.toLowerCase()) ||
          t.description.toLowerCase().includes(search.toLowerCase()),
      ),
    }))
    .filter((cat) => cat.types.length > 0);

  if (collapsed) {
    return (
      <div className="wf-palette collapsed">
        <button className="wf-palette-expand" onClick={() => setCollapsed(false)} aria-label="Expand node palette">
          <ChevronRight size={16} />
        </button>
      </div>
    );
  }

  return (
    <div className="wf-palette">
      <div className="wf-palette-header">
        <span>Nodes</span>
        <button className="wf-palette-collapse" onClick={() => setCollapsed(true)} aria-label="Collapse node palette">
          <ChevronDown size={16} />
        </button>
      </div>
      <div className="wf-palette-search">
        <Search size={14} />
        <input placeholder="Search nodes" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="wf-palette-list">
        {filtered.map((cat) => (
          <div key={cat.category} className="wf-palette-category">
            <button className="wf-palette-cat-header" onClick={() => toggleCat(cat.category)}>
              {expandedCats.has(cat.category) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span>{cat.category}</span>
            </button>
            {expandedCats.has(cat.category) && (
              <div className="wf-palette-items">
                {cat.types.map((t) => {
                  const Icon = t.icon;
                  return (
                    <div
                      key={t.type}
                      className="wf-palette-item"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData('nodeType', t.type);
                        onDragStart(t.type);
                      }}
                      title={t.description}
                    >
                      <Icon size={15} className="wf-palette-icon" />
                      <span className="wf-palette-label">{t.label}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && <div className="wf-palette-empty">No matching nodes</div>}
      </div>
    </div>
  );
}
