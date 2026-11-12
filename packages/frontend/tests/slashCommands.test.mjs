import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterSlashCommands,
  findSlashToken,
  insertSlashCommand,
  leadingCommand,
  parseArtifactCommand,
  removeLeadingCommand,
  stripSlashToken,
} from '../src/utils/slashCommands.ts';
import { parseSlides } from '../src/utils/slides.ts';

test('typing / at the start opens the command menu', () => {
  const token = findSlashToken('/');
  assert.equal(token?.query, '');
  assert.equal(token?.start, 0);
  assert.equal(findSlashToken('/ppt').query, 'ppt');
});

test('/ only opens after whitespace, not inside an email or URL', () => {
  assert.equal(findSlashToken('see https://example.com/a'), null);
  const token = findSlashToken('please /pptx', 'please /pptx'.length);
  assert.equal(token?.query, 'pptx');
  assert.equal(token?.start, 'please '.length);
});

test('filters commands by command, label and keywords', () => {
  assert.equal(filterSlashCommands('sli')[0].id, 'pptx');
  assert.equal(filterSlashCommands('powerpoint').some((item) => item.id === 'pptx'), true);
  assert.equal(filterSlashCommands('word')[0].id, 'docx');
  assert.equal(filterSlashCommands('resear')[0].id, 'research');
  assert.equal(filterSlashCommands('zzz').length, 0);
});

test('an exact command name is the default selection', () => {
  assert.equal(filterSlashCommands('pptx')[0].id, 'pptx');
  assert.equal(filterSlashCommands('docx')[0].id, 'docx');
});

test('there is exactly one presentation command', () => {
  assert.equal(filterSlashCommands('').filter((item) => item.command === '/pptx').length, 1);
  assert.equal(filterSlashCommands('').some((item) => item.command === '/slides'), false);
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
  const text = 'please /pptx about Q3';
  const token = findSlashToken('please /pptx', 'please /pptx'.length);
  assert.ok(token);
  assert.equal(stripSlashToken(text, token), 'please about Q3');
});

test('selecting a command inserts the full command into the query', () => {
  const token = findSlashToken('/ppt');
  assert.ok(token);
  const inserted = insertSlashCommand('/ppt', token, { command: '/pptx' });
  assert.equal(inserted.text, '/pptx ');
  assert.equal(inserted.cursor, '/pptx '.length);
  assert.equal(leadingCommand(inserted.text)?.id, 'pptx');
});

test('inserting keeps text typed before and after the command', () => {
  const token = findSlashToken('please /ppt');
  assert.ok(token);
  const inserted = insertSlashCommand('please /ppt now', token, { command: '/pptx' });
  assert.equal(inserted.text, 'please /pptx now');
});

test('a leading command can be removed without losing the request', () => {
  assert.equal(removeLeadingCommand('/pptx Q3 review', '/pptx'), 'Q3 review');
  assert.equal(removeLeadingCommand('/docx', '/docx'), '');
});

test('a leading backslash is accepted as a slash-command alias', () => {
  const token = findSlashToken('\\ppt');
  assert.equal(token?.query, 'ppt');
  assert.equal(leadingCommand('\\pptx Q3 review')?.id, 'pptx');
  assert.equal(parseArtifactCommand('\\pptx Q3 review')?.query, 'Q3 review');
  assert.equal(removeLeadingCommand('\\pptx Q3 review', '/pptx'), 'Q3 review');
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
