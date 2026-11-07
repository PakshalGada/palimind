import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterSlashCommands,
  findSlashToken,
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
  assert.equal(filterSlashCommands('powerpoint')[0].id, 'slides');
  assert.equal(filterSlashCommands('resear')[0].id, 'research');
  assert.equal(filterSlashCommands('zzz').length, 0);
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
