import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CREATE_ARTIFACT_OPTIONS,
  buildArtifactPrompt,
} from '../src/utils/artifactPrompts.ts';

test('offers Markdown, Word, slide and PowerPoint creation', () => {
  assert.deepEqual(
    CREATE_ARTIFACT_OPTIONS.map((option) => option.kind),
    ['document', 'word', 'slides', 'pptx', 'webpage', 'code'],
  );
  assert.equal(
    CREATE_ARTIFACT_OPTIONS.find((option) => option.kind === 'word')?.officeFormat,
    'docx',
  );
  assert.equal(
    CREATE_ARTIFACT_OPTIONS.find((option) => option.kind === 'pptx')?.officeFormat,
    'pptx',
  );
});

test('requests one fenced artifact per kind', () => {
  const document = buildArtifactPrompt('document', 'Quarterly plan');
  assert.match(document, /Quarterly plan/);
  assert.match(document, /```markdown/);

  const word = buildArtifactPrompt('word', 'Quarterly plan');
  assert.match(word, /```markdown/);
  assert.match(word, /\.docx/);

  const slides = buildArtifactPrompt('slides', 'Q3 results');
  assert.match(slides, /```slides/);
  assert.match(slides, /# heading/);

  const pptx = buildArtifactPrompt('pptx', 'Q3 results');
  assert.match(pptx, /```slides/);
  assert.match(pptx, /\.pptx/);

  const page = buildArtifactPrompt('webpage', 'Coffee roaster');
  assert.match(page, /```html/);
  assert.match(page, /<!doctype html>/i);

  const code = buildArtifactPrompt('code', 'A debounce hook');
  assert.match(code, /fenced code block/);
});

test('rejects an empty topic instead of sending a useless prompt', () => {
  assert.equal(buildArtifactPrompt('document', '   '), '');
});
