import test from 'node:test';
import assert from 'node:assert/strict';
import {
  collectArtifacts,
  nextAssistantMessageIndex,
  parseArtifactFiles,
  parseArtifacts,
} from '../src/utils/artifacts.ts';

const DOC = Array.from(
  { length: 12 },
  (_, i) => `## Section ${i + 1}\n\n${'Reliable long-form prose. '.repeat(8)}`,
).join('\n\n');

function fence(language, body, closed = true) {
  return `\`\`\`${language}\n${body}${closed ? '\n```' : ''}`;
}

test('detects an HTML fence and keeps its id stable while streaming', () => {
  const first = parseArtifacts(fence('html', '<div>hello</div>', false), 2, {
    streaming: true,
  });
  assert.equal(first.length, 1);
  assert.equal(first[0].type, 'html');
  assert.equal(first[0].id, 'fence-2-0');
  assert.equal(first[0].streaming, true);
  assert.equal(first[0].closed, false);

  const next = parseArtifacts(
    fence('html', '<div>hello world</div>\n<p>more</p>', false),
    2,
    { streaming: true },
  );
  assert.equal(next.length, 1);
  assert.equal(next[0].id, first[0].id);
  assert.match(next[0].content, /hello world/);

  const closed = parseArtifacts(
    fence('html', '<div>hello world</div>\n<p>more</p>'),
    2,
  );
  assert.equal(closed[0].id, first[0].id);
  assert.equal(closed[0].streaming, undefined);
  assert.equal(closed[0].closed, true);
});

test('treats long fenced markdown as a document', () => {
  const artifacts = parseArtifacts(`\`\`\`markdown\n${DOC}\n\`\`\``, 0);
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'document');
  assert.equal(artifacts[0].language, 'markdown');
});

test('emits a table only once it is complete', () => {
  const partial = '| Name | Value |\n| --- | --- |\n| one | 1 |';
  assert.deepEqual(
    parseArtifacts(partial, 0, { streaming: true }),
    [],
    'unterminated table should wait for more content',
  );

  const complete = `${partial}\n\nSome closing prose.`;
  const streaming = parseArtifacts(complete, 0, { streaming: true });
  assert.equal(streaming.length, 1);
  assert.equal(streaming[0].type, 'table');
  assert.equal(streaming[0].id, 'table-0-0');

  const next = parseArtifacts(`${partial}\n\nSome closing prose and more.`, 0, {
    streaming: true,
  });
  assert.equal(next[0].id, streaming[0].id, 'table id should not churn');

  const final = parseArtifacts(partial, 0);
  assert.equal(final.length, 1);
  assert.equal(final[0].type, 'table');
});

test('ignores tables inside fenced blocks', () => {
  const artifacts = parseArtifacts(
    `\`\`\`markdown\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\`\`\`\n`,
    0,
  );
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'markdown');
  assert.equal(artifacts[0].files, undefined);
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

test('parses single-file artifacts', () => {
  const artifacts = parseArtifacts(
    fence('ts', '--- file: src/app.ts ---\nexport const app = 1;'),
    0,
  );
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'code-file');
  assert.equal(artifacts[0].filePaths?.[0], 'src/app.ts');
  assert.equal(artifacts[0].files?.[0].language, 'typescript');
  assert.equal(artifacts[0].title, 'app.ts');
});

test('parses multi-file artifacts into a file list', () => {
  const body = [
    '--- file: src/app.ts ---',
    'export const app = 1;',
    '--- file: src/styles.css ---',
    'body { margin: 0; }',
    '--- file: README.md ---',
    '# Demo',
  ].join('\n');
  const artifacts = parseArtifacts(fence('', body), 0);
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'multi-file');
  assert.deepEqual(artifacts[0].filePaths, [
    'src/app.ts',
    'src/styles.css',
    'README.md',
  ]);
  assert.equal(artifacts[0].files?.length, 3);
  assert.equal(artifacts[0].files?.[1].language, 'css');
  assert.match(artifacts[0].title, /^3 files/);
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
  const mismatched = parseArtifacts('~~~html\n<div>x</div>\n```', 0);
  assert.equal(mismatched.length, 1);
  assert.equal(mismatched[0].closed, false);
  assert.equal(mismatched[0].streaming, undefined);
  assert.match(mismatched[0].content, /```/);

  const truncated = parseArtifacts('~~~html\n<div>x</div>', 0, { streaming: true });
  assert.equal(truncated[0].streaming, true);

  // Inline triple backticks are not fences.
  assert.deepEqual(parseArtifacts('Use ```code``` inline.', 0), []);

  // A fence that never opens a language is prose.
  assert.deepEqual(parseArtifacts('```\nplain text\n```', 0), []);
});

test('recognises unfenced long-form markdown only when settled', () => {
  const doc = `# Title\n\n${DOC}`;

  assert.equal(
    parseArtifacts(doc, 4, { streaming: true }).length,
    0,
    'streaming prose must not become a document per token',
  );

  const final = parseArtifacts(doc, 4);
  assert.equal(final.length, 1);
  assert.equal(final[0].type, 'document');
  assert.equal(final[0].id, 'document-4');
  assert.equal(final[0].title, 'Title');

  assert.equal(
    parseArtifacts(`# Title\n\n${'short prose '.repeat(20)}`, 4).length,
    0,
    'short prose stays in the chat',
  );
  assert.equal(
    parseArtifacts('word '.repeat(900), 4).length,
    0,
    'long prose without headings is not a document',
  );
});

test('does not duplicate an unfenced document alongside fenced artifacts', () => {
  const message = `${fence('html', '<div>app</div>')}\n\n# Notes\n\n${DOC}`;
  const artifacts = parseArtifacts(message, 1);
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].type, 'html');
});

test('collectArtifacts keeps message indices and de-duplicates ids', () => {
  const artifacts = collectArtifacts([
    { role: 'user', content: fence('html', '<div>ignored</div>') },
    { role: 'assistant', content: fence('html', '<div>one</div>') },
    { role: 'assistant', content: `Text\n\n${fence('python', 'print(1)')}` },
  ]);
  assert.deepEqual(
    artifacts.map(artifact => [artifact.id, artifact.type, artifact.messageIndex]),
    [
      ['fence-1-0', 'html', 1],
      ['fence-2-0', 'code', 2],
    ],
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
