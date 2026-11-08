import test from 'node:test';
import assert from 'node:assert/strict';
import { buildOfficePayload } from '../src/utils/officePipeline.ts';

const answer = [
  'Here is the document you asked for.',
  '',
  '```markdown',
  '# Launch plan',
  '',
  '## Summary',
  '',
  '- First point',
  '- Second point',
  '```',
].join('\n');

test('DOCX payload uses the fenced Markdown artifact, not the chat prose', () => {
  const payload = buildOfficePayload('docx', answer, 'Fallback');
  assert.equal(payload.format, 'docx');
  assert.equal(payload.title, 'Launch plan');
  assert.match(payload.content, /## Summary/);
  assert.doesNotMatch(payload.content, /Here is the document/);
});

test('PPTX payload turns a slide outline into title/bullet slides', () => {
  const deck = [
    '```slides',
    '# Overview',
    '- Point A',
    '- Point B',
    '',
    '# Results',
    '- Up 20%',
    '```',
  ].join('\n');
  const payload = buildOfficePayload('pptx', deck, 'Deck');
  assert.equal(payload.format, 'pptx');
  assert.deepEqual(payload.slides, [
    { title: 'Overview', bullets: ['Point A', 'Point B'] },
    { title: 'Results', bullets: ['Up 20%'] },
  ]);
});

test('empty answers produce no payload instead of an empty Office file', () => {
  assert.equal(buildOfficePayload('docx', '   '), null);
  assert.equal(buildOfficePayload('pptx', ''), null);
});
