import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildSourceItems,
  formatTimestamp,
  hostOf,
  localFileHref,
} from '../src/components/sources/model.ts';

const citations = {
  text: '',
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
      url: 'https://www.arxiv.org/abs/1',
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
};

test('web and document citation sources become panel items', () => {
  const items = buildSourceItems(citations);
  assert.equal(items.length, 2);
  assert.equal(items[0].kind, 'web');
  assert.equal(items[0].url, 'https://www.arxiv.org/abs/1');
  assert.equal(items[1].kind, 'document');
  assert.equal(items[1].file, 'docs/notes.md');
  assert.equal(items[1].section, 'Intro');
  assert.equal(items[1].snippet, 'A local passage');
});

test('duplicate URLs and documents are collapsed', () => {
  const items = buildSourceItems(citations, [
    { file: 'docs/notes.md', section: 'Intro' },
    { file: 'docs/notes.md', section: 'Intro' },
    { file: 'other.md', section: 'Body' },
  ]);
  assert.equal(items.length, 3);
  assert.equal(items.filter((item) => item.section === 'Intro').length, 1);
  assert.equal(items.at(-1)?.title, 'Body');
});

test('media citations keep their timestamp target', () => {
  const items = buildSourceItems(undefined, [], [
    { file: 'media/talk.mp4', start: 65, end: 70, snippet: 'A quote' },
    { file: 'media/talk.mp4', start: 65, end: 70 },
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, 'media');
  assert.equal(items[0].title, 'talk.mp4 @ 1:05');
  assert.equal(items[0].start, 65);
  assert.equal(items[0].end, 70);
});

test('legacy source strings are normalised and deduped', () => {
  const items = buildSourceItems(citations, [], [], [
    'https://www.arxiv.org/abs/1',
    'docs/notes.md',
    'docs/notes.md',
    'https://example.com/new',
  ]);
  assert.equal(items.length, 3);
  assert.equal(items.at(-1)?.kind, 'web');
  assert.equal(items.at(-1)?.title, 'example.com');
});

test('local file links encode the path and optional section', () => {
  assert.equal(localFileHref('docs/a b.md'), '/api/files/open?path=docs%2Fa+b.md');
  assert.equal(
    localFileHref('docs/a.md', 'Part 2'),
    '/api/files/open?path=docs%2Fa.md&section=Part+2',
  );
});

test('helpers format hosts and timestamps', () => {
  assert.equal(hostOf('https://www.example.com/a'), 'example.com');
  assert.equal(hostOf('not a url'), '');
  assert.equal(formatTimestamp(0), '0:00');
  assert.equal(formatTimestamp(65), '1:05');
  assert.equal(formatTimestamp(3661), '61:01');
});
