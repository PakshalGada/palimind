import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterSlashCommands,
  findSlashToken,
  parseArtifactCommand,
  stripSlashToken,
} from '../src/utils/slashCommands.ts';
import { parseSlides } from '../src/utils/slides.ts';

test('typing / at the start opens the command menu', () => {
  const token = findSlashToken('/');
  assert.equal(token?.query, '');
  assert.equal(token?.start, 0);
  assert.equal(findSlashToken('/sli').query, 'sli');
});

test('/ only opens after whitespace, not inside an email or URL', () => {
  assert.equal(findSlashToken('see https://example.com/a'), null);
  const token = findSlashToken('please /slides', 'please /slides'.length);
  assert.equal(token?.query, 'slides');
  assert.equal(token?.start, 'please '.length);
});

test('filters commands by command, label and keywords', () => {
  assert.equal(filterSlashCommands('sli')[0].id, 'slides');
  assert.equal(filterSlashCommands('powerpoint').some((item) => item.id === 'pptx'), true);
  assert.equal(filterSlashCommands('word')[0].id, 'docx');
  assert.equal(filterSlashCommands('resear')[0].id, 'research');
  assert.equal(filterSlashCommands('zzz').length, 0);
});

test('an exact command name is the default selection', () => {
  assert.equal(filterSlashCommands('pptx')[0].id, 'pptx');
  assert.equal(filterSlashCommands('docx')[0].id, 'docx');
  assert.equal(filterSlashCommands('slides')[0].id, 'slides');
});

test('there is no web-search toggle command', () => {
  assert.equal(filterSlashCommands('web').some((item) => item.id === 'web'), false);
});

test('typed artifact skills keep the user query and identify the skill', () => {
  const docx = parseArtifactCommand('/docx Q3 business review');
  assert.equal(docx?.command.skillId, 'document-docx');
  assert.equal(docx?.query, 'Q3 business review');

  const pptx = parseArtifactCommand('/pptx  Q3 results');
  assert.equal(pptx?.command.skillId, 'presentation-pptx');
  assert.equal(pptx?.query, 'Q3 results');

  assert.equal(parseArtifactCommand('/moe help'), null);
  assert.equal(parseArtifactCommand('just text'), null);

  const installed = [
    {
      id: 'skill:meeting-notes',
      command: '/meeting',
      label: 'Meeting notes',
      description: 'Summarise a meeting',
      skillId: 'meeting-notes',
    },
  ];
  const meeting = parseArtifactCommand('/meeting standup notes', installed);
  assert.equal(meeting?.command.skillId, 'meeting-notes');
  assert.equal(meeting?.query, 'standup notes');
});

test('stripping the slash token leaves the user text clean', () => {
  const text = 'please /slides about Q3';
  const token = findSlashToken('please /slides', 'please /slides'.length);
  assert.ok(token);
  assert.equal(stripSlashToken(text, token), 'please about Q3');
});

test('slide outlines parse into real slides with bullets', () => {
  const slides = parseSlides(
    ['# Title slide', '- Welcome', '', '# Roadmap', '- Ship v1', '- Ship v2', '', '# Closing', '- Questions?'].join(
      '\n',
    ),
  );
  assert.deepEqual(
    slides.map((slide) => slide.title),
    ['Title slide', 'Roadmap', 'Closing'],
  );
  assert.deepEqual(slides[1].bullets, ['Ship v1', 'Ship v2']);
});
