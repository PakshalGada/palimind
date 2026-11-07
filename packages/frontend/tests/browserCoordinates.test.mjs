import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeAddress, toPagePoint } from '../src/features/agents/browser/coordinates.ts';

test('browser pointer maps to the Playwright viewport', () => {
  const rect = { left: 110, top: 60, width: 640, height: 400 };
  const viewport = { width: 1280, height: 800 };
  assert.deepEqual(toPagePoint(110, 60, rect, viewport), { x: 0, y: 0 });
  assert.deepEqual(toPagePoint(750, 460, rect, viewport), { x: 1280, y: 800 });
  assert.deepEqual(toPagePoint(430, 260, rect, viewport), { x: 640, y: 400 });
});

test('browser pointer stays inside the viewport at the edges', () => {
  const rect = { left: 0, top: 0, width: 100, height: 100 };
  const viewport = { width: 1280, height: 800 };
  assert.deepEqual(toPagePoint(-20, -20, rect, viewport), { x: 0, y: 0 });
  assert.deepEqual(toPagePoint(140, 140, rect, viewport), { x: 1280, y: 800 });
});

test('address normalization adds https only when needed', () => {
  assert.equal(normalizeAddress('example.com'), 'https://example.com');
  assert.equal(normalizeAddress('http://example.com'), 'http://example.com');
  assert.equal(normalizeAddress('https://example.com/a?b=1'), 'https://example.com/a?b=1');
  assert.equal(normalizeAddress('  '), '');
});
