import { lazy, Suspense } from 'react';
import type { ToolStep } from '../model';
import type { ActivityStore } from '../store';
import { useActivityState } from '../hooks';
import { CodeView } from '../primitives/CodeView';
import { parseOutput, textOf, uiOf } from '../toolOutput';
import { getToolDefinition } from '../toolRegistry';

const SearchBody = lazy(() => import('./SearchBody'));
const PageBody = lazy(() => import('./PageBody'));
const FeedBody = lazy(() => import('./FeedBody'));
const FileBody = lazy(() => import('./FileBody'));
const TreeBody = lazy(() => import('./TreeBody'));
const MatchesBody = lazy(() => import('./MatchesBody'));
const DiffBody = lazy(() => import('./DiffBody'));
const PassagesBody = lazy(() => import('./PassagesBody'));
const GraphBody = lazy(() => import('./GraphBody'));
const DataBody = lazy(() => import('./DataBody'));
const CodeRunBody = lazy(() => import('./CodeRunBody'));
const TextBody = lazy(() => import('./TextBody'));
const SubagentBody = lazy(() => import('./SubagentBody'));
const BrowserBody = lazy(() => import('./BrowserBody'));
const IotBody = lazy(() => import('./IotBody'));
const WeatherBody = lazy(() => import('./WeatherBody'));
const VisualBody = lazy(() => import('./VisualBody'));
const UIBody = lazy(() => import('./UIBody'));

function GenericBody({ step }: { step: ToolStep }) {
  const output = parseOutput(step.output);
  const input = step.args;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {input != null && (
        <CodeView code={textOf(input)} language="json" title="Input" maxLines={20} copy={false} />
      )}
      {step.output != null && (
        <CodeView code={typeof output === 'string' ? output : textOf(output)} title="Output" maxLines={40} />
      )}
      {input == null && step.output == null && <div className="act-empty">No output</div>}
    </div>
  );
}

function Fallback() {
  return <div className="act-empty" style={{ minHeight: 36 }}>Loading</div>;
}

function PassagesContainer({ step, store }: { step: ToolStep; store: ActivityStore }) {
  const state = useActivityState(store);
  return <PassagesBody step={step} passages={state?.passages ?? []} />;
}

function SubagentContainer({
  step,
  store,
  depth,
}: {
  step: ToolStep;
  store: ActivityStore;
  depth: number;
}) {
  const state = useActivityState(store);
  if (!state) return null;
  return <SubagentBody step={step} state={state} store={store} depth={depth} />;
}

export function ToolBody({
  step,
  store,
  depth = 0,
  browserSteps,
}: {
  step: ToolStep;
  store: ActivityStore;
  depth?: number;
  browserSteps?: readonly ToolStep[];
}) {
  // The typed UI contract wins over the family renderer when a tool provides
  // one, so new tools can ship interactive results without a React component.
  if (uiOf(step.output)) {
    return (
      <Suspense fallback={<Fallback />}>
        <UIBody step={step} />
      </Suspense>
    );
  }
  const family = getToolDefinition(step.name).family;
  let body: React.ReactNode;
  switch (family) {
    case 'search':
      body = <SearchBody step={step} />;
      break;
    case 'page':
      body = <PageBody step={step} />;
      break;
    case 'feed':
      body = <FeedBody step={step} />;
      break;
    case 'file':
      body = <FileBody step={step} />;
      break;
    case 'tree':
      body = <TreeBody step={step} />;
      break;
    case 'matches':
      body = <MatchesBody step={step} />;
      break;
    case 'diff':
      body = <DiffBody step={step} />;
      break;
    case 'passages':
      body = <PassagesContainer step={step} store={store} />;
      break;
    case 'graph':
      body = <GraphBody step={step} />;
      break;
    case 'data':
      body = <DataBody step={step} />;
      break;
    case 'code-run':
      body = <CodeRunBody step={step} store={store} />;
      break;
    case 'text':
      body = <TextBody step={step} />;
      break;
    case 'subagent':
      body = <SubagentContainer step={step} store={store} depth={depth} />;
      break;
    case 'browser':
      body = <BrowserBody steps={browserSteps ?? [step]} />;
      break;
    case 'iot':
      body = <IotBody step={step} />;
      break;
    case 'weather':
      body = <WeatherBody step={step} />;
      break;
    case 'visual':
      body = <VisualBody step={step} />;
      break;
    default:
      body = <GenericBody step={step} />;
  }
  return <Suspense fallback={<Fallback />}>{body}</Suspense>;
}
