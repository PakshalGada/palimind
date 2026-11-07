/**
 * Render smoke test: server-render the redesigned activity surfaces and assert
 * the strings and affordances that matter. Run by `npm run test:render`.
 */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ActivityPanel } from '../src/components/activity/shell/ActivityPanel';
import { PermissionGrant } from '../src/components/activity/shell/PermissionGrant';
import { ComposerCaption } from '../src/components/ComposerCaption';
import { PhaseSpine } from '../src/components/activity/shell/PhaseSpine';
import { ActivityStore } from '../src/components/activity/store';
import { RunSurface } from '../src/components/activity/shell/RunSurface';
import { SourcesPanel } from '../src/components/sources/SourcesPanel';
import { ActivitySurfaceContext } from '../src/stream/context';
import type { ActivityState } from '../src/components/activity/model';
import ComputerUsePanel from '../src/features/desktop/ComputerUsePanel';
import { LiveRunFooter } from '../src/stream/StreamingMessage';
import ScreenRegionOverlay from '../src/features/desktop/ScreenRegionOverlay';
import { GhostCursorMark, targetFromSearch } from '../src/features/desktop/GhostCursorOverlay';
import { ApprovalCard } from '../src/features/desktop/ComputerUsePanel';

const now = 1_000_000;

function settled(): ActivityState {
  return {
    runId: 'smoke-settled',
    mode: 'agent',
    status: 'done',
    startedAt: now - 12_400,
    endedAt: now,
    steps: [
      {
        id: 's1',
        name: 'web_search',
        status: 'success',
        args: { query: 'retrieval' },
        output: [
          { title: 'A', url: 'https://arxiv.org/abs/1', domain: 'arxiv.org' },
          { title: 'B', url: 'https://example.com/2', domain: 'example.com' },
        ],
        startedAt: now - 11_000,
        endedAt: now - 9_600,
        durationMs: 1400,
      },
      {
        id: 's2',
        name: 'fetch_url',
        status: 'success',
        args: { url: 'https://arxiv.org/abs/1' },
        startedAt: now - 9_500,
        endedAt: now - 8_000,
        durationMs: 1500,
      },
    ],
    sources: [
      { id: 'w1', title: 'A', url: 'https://arxiv.org/abs/1', domain: 'arxiv.org' },
      { id: 'w2', title: 'B', url: 'https://example.com/2', domain: 'example.com' },
    ],
    passages: [],
    answerStarted: true,
    reasoning: {
      text: 'Retrieval first, then rerank.',
      done: true,
      startedAt: now - 12_000,
      durationMs: 8_000,
    },
  };
}

function pending(): ActivityState {
  return {
    runId: 'smoke-pending',
    mode: 'agent',
    status: 'awaiting_approval',
    startedAt: now - 30_000,
    steps: [
      {
        id: 'p1',
        name: 'run_shell',
        status: 'awaiting_approval',
        args: { command: 'rm -rf build && npm test -- --token=super-secret-token' },
        startedAt: now - 1_000,
        approval: { agentId: 'a1', runId: 'smoke-pending', tool: 'run_shell' },
      },
    ],
    sources: [],
    passages: [],
    answerStarted: false,
  };
}

function failed(): ActivityState {
  return {
    runId: 'smoke-failed',
    mode: 'default',
    status: 'error',
    startedAt: now - 5000,
    endedAt: now,
    steps: [
      {
        id: 'f1',
        name: 'web_search',
        status: 'error',
        args: { query: 'x' },
        error: 'Rate limited',
        startedAt: now - 4000,
        endedAt: now - 3000,
        durationMs: 1000,
      },
    ],
    sources: [],
    passages: [],
    answerStarted: false,
  };
}

function noop() {}

let failures = 0;
function check(label: string, html: string, needles: string[], forbidden: string[] = []) {
  const missing = needles.filter((needle) => !html.includes(needle));
  const unexpected = forbidden.filter((needle) => html.includes(needle));
  if (missing.length || unexpected.length) {
    failures += 1;
    console.error(`FAIL ${label}`);
    if (missing.length) console.error('  missing:', missing);
    if (unexpected.length) console.error('  unexpected:', unexpected);
  } else {
    console.log(`PASS ${label}`);
  }
}

// 1. Settled panel: caption, reasoning one-liner, clustered research, sources.
const settledState = settled();
const settledStore = ActivityStore.fromState(settledState);
const settledHtml = renderToStaticMarkup(
  React.createElement(ActivityPanel, {
    state: settledState,
    store: settledStore,
    history: true,
    onRetryRun: noop,
  }),
);
check(
  'settled panel',
  settledHtml,
  ['act-panel', 'Thought for 8s', 'ac-caption placeholder'.replace('ac-caption placeholder', 'act-caption'), '2 sources', 'Searched 2 sources', 'act--static'],
  ['act-attention', 'ac-grant'],
);

// 2. Live pending approval: caption, grant copy, masked secret, buttons.
const pendingState = pending();
const pendingStore = new ActivityStore(pendingState);
const pendingHtml = renderToStaticMarkup(
  React.createElement(ActivityPanel, { state: pendingState, store: pendingStore, onResolveApproval: noop }),
);
check(
  'pending approval panel',
  pendingHtml,
  [
    'Needs approval',
    'Allow once',
    'Allow for this run',
    'Deny',
    'Review carefully',
    'Run rm -rf build',
    'act-attention',
    'act-spine',
  ],
  ['super-secret-token'],
);

// 3. Failed run: failed caption and error row affordances.
const failedState = failed();
const failedStore = new ActivityStore(failedState);
const failedHtml = renderToStaticMarkup(
  React.createElement(ActivityPanel, { state: failedState, store: failedStore, onRetryRun: noop }),
);
check('failed panel', failedHtml, ['Failed — 1 step', 'act-panel--error', 'Rate limited'], []);

// 4. Restored pending approval: "Requested earlier", no pulse.
const restoredStore = ActivityStore.fromState(pendingState);
const restoredHtml = renderToStaticMarkup(
  React.createElement(ActivityPanel, {
    state: pendingState,
    store: restoredStore,
    history: true,
    onResolveApproval: noop,
  }),
);
check('restored approval', restoredHtml, ['Requested earlier', 'Needs approval'], ['act-attention']);

// 4b. Agent todo checklist: progress count and all three statuses.
const todoState: ActivityState = {
  ...settled(),
  runId: 'smoke-todo',
  status: 'working',
  endedAt: undefined,
  plan: [
    { id: '1', label: 'Find sources', status: 'done' },
    { id: '2', label: 'Read pages', status: 'running' },
    { id: '3', label: 'Write brief', status: 'pending' },
  ],
};
const todoHtml = renderToStaticMarkup(
  React.createElement(ActivityPanel, {
    state: todoState,
    store: new ActivityStore(todoState),
  }),
);
check(
  'agent todo checklist',
  todoHtml,
  ['Plan · 1/3 done', 'Find sources', 'Read pages', 'Write brief', 'act-plan__item--running'],
  [],
);

// 4c. Live answer footer: token/cost chip, escalation and follow-up chips.
const streamHtml = renderToStaticMarkup(
  React.createElement(LiveRunFooter, {
    usage: { prompt_tokens: 1200, completion_tokens: 800, estimated_cost_usd: 0 },
    escalation: 'Escalated to strong-model',
    suggestions: ['What are the takeaways?', 'Compare the sources.'],
    settled: true,
  }),
);
check(
  'stream usage and follow-ups',
  streamHtml,
  ['Escalated to strong-model', '1.2k in', '800 out', 'local · $0', 'What are the takeaways?', 'Compare the sources.'],
  [],
);

// 5. PermissionGrant standalone: browser action + keyboard hint.
const browserStep = {
  id: 'b1',
  name: 'browser_click',
  status: 'awaiting_approval' as const,
  args: { label: 'Sign in', url: 'https://example.com/docs' },
};
const grantHtml = renderToStaticMarkup(
  React.createElement(PermissionGrant, { step: browserStep, allowedForRun: false, onResolve: noop }),
);
check(
  'browser grant',
  grantHtml,
  [
    'Click &quot;Sign in&quot; on example.com',
    'Enter allow once · A allow for this run · Esc deny',
    'Needs approval',
  ],
);

// 6. Composer caption line inside the shared surface context.
const composerHtml = renderToStaticMarkup(
  React.createElement(
    ActivitySurfaceContext.Provider,
    { value: { store: pendingStore, lastActivity: null } },
    React.createElement(ComposerCaption),
  ),
);
check('composer caption', composerHtml, ['Needs approval', 'act-caption-line', 'pixel-icon']);

// 7. Phase spine renders three equal segments.
const spineHtml = renderToStaticMarkup(React.createElement(PhaseSpine, { phase: 'reading' }));
check('phase spine', spineHtml, ['act-spine', 'act-spine__seg--active', 'act-spine__seg--todo']);


// 8. Every mode renderer mounts through RunSurface without crashing.
function modeState(mode: ActivityState['mode']): ActivityState {
  return {
    runId: `smoke-${mode}`,
    mode,
    status: 'working',
    startedAt: now - 6_000,
    steps: [
      {
        id: 'm1',
        name: mode === 'knowledge_base' ? 'document_search' : 'web_search',
        status: 'running',
        args: { query: 'retrieval' },
        startedAt: now - 1_000,
      },
    ],
    sources: [],
    passages:
      mode === 'knowledge_base'
        ? [{ id: 'k1', docId: 'notes.md', docName: 'notes.md', page: 2, text: 'Matched passage.' }]
        : [],
    answerStarted: false,
    phase: mode === 'moe' ? 'analyzing' : 'searching',
    plan: undefined,
    experts:
      mode === 'moe'
        ? [
            { id: 'e1', name: 'Retrieval expert', status: 'running' },
            { id: 'e2', name: 'Evaluation expert', status: 'done' },
          ]
        : undefined,
  };
}

for (const mode of ['default', 'moe', 'deep_research', 'knowledge_base', 'agent'] as const) {
  const state = modeState(mode);
  const store = new ActivityStore(state);
  const html = renderToStaticMarkup(
    React.createElement(RunSurface, { store, onRetryRun: noop, onResolveApproval: noop }),
  );
  check(`mode: ${mode}`, html, ['act-panel', 'act-caption']);
}

// 9. Sources panel: inline chips for web/document/media citations.
const sourcesHtml = renderToStaticMarkup(
  React.createElement(SourcesPanel, {
    citations: {
      citations: [],
      bibliography: '',
      accuracy: 0,
      coverage: 0,
      mean_score: 0,
      cited_markers: [],
      sources: [
        {
          marker: 1,
          title: 'Retrieval paper',
          kind: 'web',
          url: 'https://arxiv.org/abs/1',
          file: '',
          section: '',
          snippet: 'A web result',
          content: '',
          score: 1,
        },
        {
          marker: 2,
          title: 'notes.md',
          kind: 'document',
          url: '',
          file: 'docs/notes.md',
          section: 'Intro',
          snippet: 'A local passage',
          content: '',
          score: 1,
        },
      ],
    },
    mediaCitations: [{ file: 'media/talk.mp4', start: 65, end: 70 }],
    onOpenVideo: noop,
  }),
);
check(
  'sources panel',
  sourcesHtml,
  [
    'sources-panel__chips',
    'Retrieval paper',
    'notes.md',
    'Sources · 3',
    'href="https://arxiv.org/abs/1"',
    'href="/api/files/open?path=docs%2Fnotes.md&amp;section=Intro"',
    'talk.mp4 @ 1:05',
  ],
  ['sources-drawer__backdrop'],
);

const popupHtml = renderToStaticMarkup(React.createElement(ComputerUsePanel));
check('computer use popup', popupHtml, [
  'Computer Use',
  'Any app',
  'Target',
  'Select area',
  'Request',
  'Ask',
  'read-only',
  'Act',
  'approve each step',
  'Stop',
  'Send',
  'Switch model',
  'Select model',
]);

const overlayHtml = renderToStaticMarkup(React.createElement(ScreenRegionOverlay));
check('computer use region overlay', overlayHtml, [
  'Drag to select an area',
  'Esc to cancel',
]);

const ghostHtml = renderToStaticMarkup(
  React.createElement(GhostCursorMark, {
    target: { x: 120, y: 240, width: 160, height: 48, label: 'Save button' },
  }),
);
check('computer use ghost cursor', ghostHtml, [
  'cu-ghost__ring',
  'cu-ghost__box',
  'Save button',
  'left:120px',
  'width:160px',
]);

const parsedGhost = targetFromSearch(
  '?window=cursor-ghost&x=10&y=20&w=30&h=40&label=Export',
);
if (!parsedGhost || parsedGhost.x !== 10 || parsedGhost.y !== 20 || parsedGhost.label !== 'Export') {
  failures += 1;
  console.error('FAIL ghost cursor url parsing', parsedGhost);
} else {
  console.log('PASS ghost cursor url parsing');
}

const approvalHtml = renderToStaticMarkup(
  React.createElement(ApprovalCard, {
    tool: 'desktop_act',
    args: { action: 'click', ref: '@s1:e7' },
    onDecide: () => {},
  }),
);
check('computer use approval card', approvalHtml, [
  'Approval needed',
  'desktop_act',
  'action: click',
  'Approve',
  'Deny',
]);

console.log(failures === 0 ? 'SMOKE OK' : `SMOKE FAILED (${failures})`);
process.exit(failures === 0 ? 0 : 1);

// DEBUG dump for the pending panel
