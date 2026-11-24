import test from 'node:test';
import assert from 'node:assert/strict';
import { buildArtifactOfficePayload, buildOfficePayload } from '../src/utils/officePipeline.ts';

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
  assert.deepEqual(
    payload.slides.map(({ title, bullets }) => ({ title, bullets })),
    [
      { title: 'Overview', bullets: ['Point A', 'Point B'] },
      { title: 'Results', bullets: ['Up 20%'] },
    ],
  );
});

test('empty answers produce no payload instead of an empty Office file', () => {
  assert.equal(buildOfficePayload('docx', '   '), null);
  assert.equal(buildOfficePayload('pptx', ''), null);
});

test('artifact previews use the same Office payload as the composer', () => {
  const doc = buildArtifactOfficePayload(
    { type: 'document', title: 'Launch plan', content: '# Launch plan\n\n- Ship it' },
    'docx',
  );
  assert.equal(doc.format, 'docx');
  assert.equal(doc.title, 'Launch plan');
  assert.match(doc.content, /Ship it/);

  const deck = buildArtifactOfficePayload(
    { type: 'slide-outline', title: 'Board deck', content: '# Overview\n- Point A\n\n# Results\n- Up 20%' },
    'pptx',
  );
  assert.equal(deck.format, 'pptx');
  assert.deepEqual(
    deck.slides.map(({ title, bullets }) => ({ title, bullets })),
    [
      { title: 'Overview', bullets: ['Point A'] },
      { title: 'Results', bullets: ['Up 20%'] },
    ],
  );
});

test('PPTX payload keeps chart directives and layout hints', () => {
  const deck = [
    '```slides',
    '# Revenue grew 18%',
    '- Growth accelerated',
    '[chart: bar] Quarterly revenue ($M) | Q1: 4.2 | Q2: 5.1 | Q3: 6.0',
    '',
    '# Performance [layout: metrics]',
    '- Revenue: $6.0M',
    '- Growth: 18%',
    '```',
  ].join('\n');
  const payload = buildOfficePayload('pptx', deck, 'Deck');
  assert.equal(payload?.slides?.[0]?.layout, 'chart');
  assert.equal(payload?.slides?.[0]?.chart?.values?.[2], 6);
  assert.equal(payload?.slides?.[1]?.layout, 'metrics');
});
