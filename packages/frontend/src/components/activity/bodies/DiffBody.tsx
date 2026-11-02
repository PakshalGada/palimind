import { lazy, Suspense } from 'react';
import type { ToolStep } from '../model';
import { CodeView } from '../primitives/CodeView';
import { diffFromStep } from '../toolOutput';

const DiffView = lazy(() =>
  import('../primitives/DiffView').then((module) => ({ default: module.DiffView })),
);

export default function DiffBody({ step }: { step: ToolStep }) {
  const diff = diffFromStep(step.output, step.args);
  if (diff.isNew && !diff.before) {
    return (
      <div>
        <div className="act-section-title">{diff.path}</div>
        <CodeView code={diff.after ?? ''} title={diff.path} lineNumbers maxLines={60} />
      </div>
    );
  }
  if (!diff.before && !diff.after) {
    return <div className="act-empty">No changes</div>;
  }
  return (
    <div>
      <div className="act-section-title">{diff.path}</div>
      <Suspense fallback={<div className="act-empty">Loading diff</div>}>
        <DiffView before={diff.before ?? ''} after={diff.after ?? ''} path={diff.path} />
      </Suspense>
    </div>
  );
}
