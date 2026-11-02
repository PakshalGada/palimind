import test from 'node:test';
import assert from 'node:assert/strict';
import {
  adaptRun,
  modeFromActivityMode,
  modeFromSubMode,
  stepsFromTrace,
} from '../src/components/activity/adaptRun.ts';
import { TOOL_COUNT, TOOL_REGISTRY, getToolDefinition, normalizeToolName, previewForTool } from '../src/components/activity/toolRegistry.ts';

test('all 47 tools are registered with complete metadata', () => {
  assert.equal(TOOL_COUNT, 47);
  for (const [name, entry] of Object.entries(TOOL_REGISTRY)) {
    assert.ok(entry.icon, `${name} has an icon`);
    assert.ok(entry.running.length > 0, `${name} has a running label`);
    assert.ok(entry.done.length > 0, `${name} has a done label`);
    assert.ok(entry.family, `${name} has a family`);
    assert.equal(typeof entry.preview, 'function', `${name} has a preview extractor`);
    assert.ok(!entry.running.endsWith('…'), `${name} running label has no ellipsis`);
    assert.ok(!entry.running.includes('!'), `${name} running label has no exclamation`);
    assert.notEqual(entry.running, entry.done, `${name} running and done labels differ`);
  }
});

test('exactly the seven approval tools are marked', () => {
  const approvals = Object.entries(TOOL_REGISTRY)
    .filter(([, entry]) => entry.approval)
    .map(([name]) => name)
    .sort();
  assert.deepEqual(approvals, [
    'browser_click',
    'browser_press',
    'browser_type',
    'run_python',
    'run_shell',
    'search_replace',
    'write_file',
  ]);
});

test('unknown tools humanize and never show snake case', () => {
  const definition = getToolDefinition('some_new_tool');
  assert.equal(definition.family, 'generic');
  assert.equal(definition.icon, 'wrench');
  assert.equal(previewForTool('some_new_tool', { input: 'value' }), 'value');
});

test('tool names normalize hyphens, spaces and dots', () => {
  assert.equal(normalizeToolName('web-search'), 'web_search');
  assert.equal(normalizeToolName('Web Search'), 'web_search');
  assert.equal(normalizeToolName('tools.web_search'), 'web_search');
});

test('preview extractors pick the useful argument', () => {
  assert.equal(previewForTool('web_search', { query: 'retrieval depth' }), 'retrieval depth');
  assert.equal(previewForTool('read_file', { path: 'src/agents/runtime.ts' }), 'runtime.ts');
  assert.equal(previewForTool('run_shell', { command: 'npm test\nsecond line' }), 'npm test');
  assert.equal(previewForTool('sqlite_query', { sql: 'SELECT *\nFROM docs' }), 'SELECT *');
  assert.equal(previewForTool('run_python', { code: 'print(1)\nprint(2)' }), 'print(1)');
  assert.equal(previewForTool('browser_type', { label: 'Password', text: 'hunter2' }), 'Password ********');
  assert.equal(previewForTool('browser_click', { label: 'Sign in' }), 'Sign in');
  assert.equal(previewForTool('open_meteo', { latitude: 51.5, longitude: -0.1 }), '51.5, -0.1');
  assert.equal(previewForTool('fetch_url', { url: 'https://www.example.com/a' }), 'example.com');
});

test('mode mapping covers every product area', () => {
  assert.equal(modeFromActivityMode('document'), 'knowledge_base');
  assert.equal(modeFromActivityMode('moe'), 'moe');
  assert.equal(modeFromActivityMode('deep_research'), 'deep_research');
  assert.equal(modeFromActivityMode('agent'), 'agent');
  assert.equal(modeFromActivityMode('llm'), 'default');
  assert.equal(modeFromSubMode('moe'), 'moe');
  assert.equal(modeFromSubMode(undefined), 'default');
});

test('adaptRun derives tools, sources and passages', () => {
  const state = adaptRun({
    runId: 'run-1',
    mode: 'knowledge_base',
    startedAt: 1000,
    status: 'done',
    endedAt: 4000,
    thinking: 'Looking through notes',
    legacy: {
      mode: 'document',
      title: 'Document',
      steps: [
        {
          id: 's1',
          kind: 'tool',
          title: 'Search documents',
          tool: 'document_search',
          detail: '{"query":"retrieval"}',
          result: '2 passages',
          status: 'done',
          startedAt: 1100,
          completedAt: 1400,
        },
      ],
    },
    citations: {
      sources: [
        {
          marker: 1,
          title: 'Retrieval notes',
          kind: 'document',
          url: '',
          file: 'notes/retrieval.md',
          section: 'Intro',
          snippet: 'Hybrid search combines dense and sparse signals.',
          content: '',
          score: 0.9,
        },
        {
          marker: 2,
          title: 'Example result',
          kind: 'web',
          url: 'https://example.com/a',
          file: '',
          section: '',
          snippet: 'A web result',
          content: '',
          score: 0.5,
        },
      ],
      citations: [],
      bibliography: '',
      accuracy: 0,
      coverage: 0,
      mean_score: 0,
      cited_markers: [],
    },
  });
  assert.equal(state.mode, 'knowledge_base');
  assert.equal(state.steps.length, 1);
  assert.equal(state.steps[0].name, 'document_search');
  assert.equal(state.steps[0].durationMs, 300);
  assert.equal(state.sources.length, 1);
  assert.equal(state.sources[0].domain, 'example.com');
  assert.equal(state.passages.length, 1);
  assert.equal(state.passages[0].docName, 'retrieval.md');
  assert.equal(state.reasoning.text, 'Looking through notes');
});

test('stepsFromTrace pairs calls with results and marks errors', () => {
  const steps = stepsFromTrace([
    { type: 'agent:tool_call', tool: 'web-search', args: { query: 'a' } },
    { type: 'agent:tool_result', result: 'Error: blocked' },
    { type: 'agent:tool_call', tool: 'read_file', args: { path: 'a.ts' } },
    { type: 'agent:tool_result', result: 'ok' },
  ]);
  assert.equal(steps.length, 2);
  assert.equal(steps[0].name, 'web_search');
  assert.equal(steps[0].status, 'error');
  assert.equal(steps[1].status, 'success');
});
