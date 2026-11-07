import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CREATE_ARTIFACT_OPTIONS,
  buildArtifactPrompt,
} from '../src/utils/artifactPrompts.ts';

test('offers document, slides, web page and code creation', () => {
  assert.deepEqual(
    CREATE_ARTIFACT_OPTIONS.map((option) => option.kind),
    ['document', 'slides', 'webpage', 'code'],
  );
});

test('requests one fenced artifact per kind', () => {
  const document = buildArtifactPrompt('document', 'Quarterly plan');
  assert.match(document, /Quarterly plan/);
  assert.match(document, /```markdown/);

  const slides = buildArtifactPrompt('slides', 'Q3 results');
  assert.match(slides, /```slides/);
  assert.match(slides, /# heading/);

  const page = buildArtifactPrompt('webpage', 'Coffee roaster');
  assert.match(page, /```html/);
  assert.match(page, /<!doctype html>/i);

  const code = buildArtifactPrompt('code', 'A debounce hook');
  assert.match(code, /fenced code block/);
});

test('rejects an empty topic instead of sending a useless prompt', () => {
  assert.equal(buildArtifactPrompt('document', '   '), '');
});
