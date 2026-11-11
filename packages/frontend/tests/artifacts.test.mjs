import test from 'node:test';
import assert from 'node:assert/strict';
import {
  collectArtifacts,
  nextAssistantMessageIndex,
  parseArtifactFiles,
  parseArtifacts,
  shouldAutoOpenArtifact,
} from '../src/utils/artifacts.ts';

const DOC = Array.from(
  { length: 12 },
  (_, i) => `## Section ${i + 1}\n\n${'Reliable long-form prose. '.repeat(8)}`,
).join('\n\n');

function fence(language, body, closed = true) {
  return `\`\`\`${language}\n${body}${closed ? '\n```' : ''}`;
}

test('HTML fences create previewable artifacts', () => {
  for (const language of ['html', 'htm']) {
    const artifacts = parseArtifacts(fence(language, '<div>hello</div>'), 2);
    assert.equal(artifacts.length, 1, language);
    assert.equal(artifacts[0].type, 'html', language);
    assert.equal(artifacts[0].id, 'fence-2-0', language);
    assert.equal(artifacts[0].content, '<div>hello</div>', language);
  }
  assert.deepEqual(
    parseArtifacts(fence('svg', '<svg></svg>'), 2),
    [],
  );
});

test('keeps a slide artifact id stable while streaming', () => {
  const first = parseArtifacts(fence('slides', '# Intro\n- one', false), 2, {
    streaming: true,
  });
  assert.equal(first.length, 1);
  assert.equal(first[0].type, 'slide-outline');
  assert.equal(first[0].id, 'fence-2-0');
  assert.equal(first[0].streaming, true);
  assert.equal(first[0].closed, false);

  const next = parseArtifacts(
    fence('slides', '# Intro\n- one\n- two', false),
    2,
    { streaming: true },
  );
  assert.equal(next.length, 1);
  assert.equal(next[0].id, first[0].id);
  assert.match(next[0].content, /two/);

  const closed = parseArtifacts(fence('slides', '# Intro\n- one\n- two'), 2);
  assert.equal(closed[0].id, first[0].id);
  assert.equal(closed[0].streaming, undefined);
  assert.equal(closed[0].closed, true);
});

test('keeps Markdown fences inline instead of creating artifacts', () => {
  assert.deepEqual(parseArtifacts(`\`\`\`markdown\n${DOC}\n\`\`\``, 0), []);
  assert.deepEqual(parseArtifacts(fence('md', '# Title\n\nShort note.'), 0), []);
});

test('keeps explicit office documents as artifacts', () => {
  const artifacts = parseArtifacts(fence('docx', '# Title\n\nBody'), 0);
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'document');
  assert.equal(artifacts[0].language, 'docx');
});

test('keeps Markdown tables inline instead of creating artifacts', () => {
  const table = '| Name | Value |\n| --- | --- |\n| one | 1 |';
  assert.deepEqual(parseArtifacts(table, 0, { streaming: true }), []);
  assert.deepEqual(parseArtifacts(`${table}\n\nClosing prose.`, 0), []);
});

test('ignores Markdown fences and their tables', () => {
  const artifacts = parseArtifacts(
    `\`\`\`markdown\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\`\`\`\n`,
    0,
  );
  assert.deepEqual(artifacts, []);
});

test('detects slide outlines', () => {
  const artifacts = parseArtifacts(
    fence('slides', '# Intro\n\n- First point\n\n# Second slide\n\n- Another point'),
    0,
  );
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'slide-outline');
  assert.equal(artifacts[0].language, 'slides');
});

test('code fences stay inline instead of creating artifacts', () => {
  assert.deepEqual(
    parseArtifacts(fence('ts', '--- file: src/app.ts ---\nexport const app = 1;'), 0),
    [],
  );
  const body = [
    '--- file: src/app.ts ---',
    'export const app = 1;',
    '--- file: src/styles.css ---',
    'body { margin: 0; }',
  ].join('\n');
  assert.deepEqual(parseArtifacts(fence('', body), 0), []);
});

test('parseArtifactFiles ignores preamble and trims bodies', () => {
  const files = parseArtifactFiles(
    'ignored preamble\n--- file: a.py ---\n\nprint(1)\n\n--- file: b.sh ---\necho hi\n',
  );
  assert.equal(files.length, 2);
  assert.equal(files[0].path, 'a.py');
  assert.equal(files[0].content, 'print(1)');
  assert.equal(files[0].language, 'python');
  assert.equal(files[1].language, 'bash');
});

test('handles malformed and truncated fences', () => {
  // A tilde fence must not be closed by backticks.
  const mismatched = parseArtifacts('~~~slides\n# Slide\n```', 0);
  assert.equal(mismatched.length, 1);
  assert.equal(mismatched[0].closed, false);
  assert.equal(mismatched[0].streaming, undefined);
  assert.match(mismatched[0].content, /```/);

  const truncated = parseArtifacts('~~~slides\n# Slide', 0, { streaming: true });
  assert.equal(truncated[0].streaming, true);

  // Inline triple backticks are not fences.
  assert.deepEqual(parseArtifacts('Use ```code``` inline.', 0), []);

  // A fence that never opens a language is prose.
  assert.deepEqual(parseArtifacts('```\nplain text\n```', 0), []);
});

test('never turns unfenced prose into a document artifact', () => {
  const doc = `# Title\n\n${DOC}`;
  assert.deepEqual(parseArtifacts(doc, 4), []);
  assert.deepEqual(parseArtifacts(doc, 4, { streaming: true }), []);
  assert.deepEqual(parseArtifacts(`# Title\n\n${'short prose '.repeat(20)}`, 4), []);
});

test('does not add a Markdown artifact next to an office artifact', () => {
  const message = `${fence('slides', '# Deck\n- point')}\n\n# Notes\n\n${DOC}`;
  const artifacts = parseArtifacts(message, 1);
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'slide-outline');
});

test('collectArtifacts keeps message indices and de-duplicates ids', () => {
  const artifacts = collectArtifacts([
    { role: 'user', content: fence('slides', '# ignored') },
    { role: 'assistant', content: fence('slides', '# Deck\n- one') },
    { role: 'assistant', content: `Text\n\n${fence('docx', '# Report')}` },
  ]);
  assert.deepEqual(
    artifacts.map(artifact => [artifact.id, artifact.type, artifact.messageIndex]),
    [
      ['fence-1-0', 'slide-outline', 1],
      ['fence-2-0', 'document', 2],
    ],
  );
});

test('auto-opens HTML and Office/PowerPoint artifacts', () => {
  assert.equal(shouldAutoOpenArtifact({ type: 'html' }), true);
  assert.equal(shouldAutoOpenArtifact({ type: 'document' }), true);
  assert.equal(shouldAutoOpenArtifact({ type: 'slide-outline' }), true);
  for (const type of ['svg', 'markdown', 'table', 'code', 'code-file', 'multi-file']) {
    assert.equal(shouldAutoOpenArtifact({ type }), false, type);
  }
  assert.equal(
    shouldAutoOpenArtifact({ type: 'code-file', filePaths: ['notes.md'] }),
    false,
  );
  assert.equal(
    shouldAutoOpenArtifact({ type: 'code-file', filePaths: ['report.docx'] }),
    true,
  );
});

test('predicts the message index the live assistant will persist at', () => {
  assert.equal(nextAssistantMessageIndex([]), 1);
  assert.equal(
    nextAssistantMessageIndex([{ role: 'user', content: 'hi' }]),
    1,
    'stored user message means the assistant follows it',
  );
  assert.equal(
    nextAssistantMessageIndex([
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'hello' },
    ]),
    3,
    'the in-flight user message is not in the session yet',
  );
  assert.equal(
    nextAssistantMessageIndex([
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'hello' },
      { role: 'user', content: 'again' },
    ]),
    3,
  );
});
