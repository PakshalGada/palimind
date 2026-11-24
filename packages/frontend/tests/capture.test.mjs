import test from 'node:test';
import assert from 'node:assert/strict';
import { dataUrlToFile, fileToBase64 } from '../src/utils/capture.ts';

const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

test('data URL conversion produces a typed image file', () => {
  const file = dataUrlToFile(pixel, 'clipboard.png');
  assert.ok(file);
  assert.equal(file?.name, 'clipboard.png');
  assert.equal(file?.type, 'image/png');
  assert.ok((file?.size ?? 0) > 0);
});

test('invalid data URLs are rejected', () => {
  assert.equal(dataUrlToFile('not-a-data-url', 'x.png'), null);
});


test('fileToBase64 encodes file contents', async () => {
  const file = new File(['hello'], 'hello.txt', { type: 'text/plain' });
  assert.equal(await fileToBase64(file), Buffer.from('hello').toString('base64'));
});
