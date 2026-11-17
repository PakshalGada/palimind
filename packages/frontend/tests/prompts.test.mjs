import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  promptToSlashCommand,
  renderPromptTemplate,
  templateVariables,
} from '../src/utils/prompts.ts';

test('templateVariables extracts unique names in order', () => {
  assert.deepEqual(templateVariables('Summarise {url} for {audience} ({url} again)'), [
    'url',
    'audience',
  ]);
  assert.deepEqual(templateVariables('no variables here'), []);
  assert.deepEqual(templateVariables('{0nly digits} {ok-name} {x}'), ['ok-name', 'x']);
});

test('renderPromptTemplate fills values and keeps missing placeholders', () => {
  assert.equal(
    renderPromptTemplate('Plan {week} for {team}.', { week: '48', team: 'Core' }),
    'Plan 48 for Core.',
  );
  assert.equal(
    renderPromptTemplate('Plan {week} for {team}.', { week: '48' }),
    'Plan 48 for {team}.',
  );
  assert.equal(renderPromptTemplate('Static text.', {}), 'Static text.');
  // Whitespace-only values count as missing.
  assert.equal(renderPromptTemplate('Ask {q} please', { q: '   ' }), 'Ask {q} please');
});

test('promptToSlashCommand builds a composer entry', () => {
  const slash = promptToSlashCommand({
    id: 'abc123',
    name: 'Paper Summary',
    command: 'paper-summary',
    template: 'Summarise {url}.',
    description: 'Summarise a paper',
  });
  assert.equal(slash.id, 'prompt:abc123');
  assert.equal(slash.command, '/paper-summary');
  assert.equal(slash.label, 'Paper Summary');
  assert.equal(slash.description, 'Summarise a paper');
  assert.equal(slash.promptId, 'abc123');
  assert.equal(slash.template, 'Summarise {url}.');

  // Without a description the template preview stands in.
  const noDesc = promptToSlashCommand({
    id: 'x',
    name: 'N',
    command: 'n',
    template: 'A   template\non two lines',
  });
  assert.equal(noDesc.description, 'A template on two lines');
});
