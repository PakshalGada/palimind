import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveScope, scopeLabel } from '../src/lib/scope.ts';

test('agents never fall back to global chat', () => {
  assert.equal(resolveScope('agents'), '');
  assert.equal(resolveScope('agents', { agentId: 'a1', projectId: 'p1' }), 'agent:a1');
});

test('home and chat share the global chat scope', () => {
  assert.equal(resolveScope('home'), 'chat');
  assert.equal(resolveScope('chat'), 'chat');
});

test('a project wins for home, chat and knowledge', () => {
  assert.equal(resolveScope('home', { projectId: 'p1' }), 'project:p1');
  assert.equal(resolveScope('chat', { projectId: 'p1' }), 'project:p1');
  assert.equal(resolveScope('knowledge', { projectId: 'p1' }), 'project:p1');
});

test('knowledge defaults to the field scope', () => {
  assert.equal(resolveScope('knowledge'), 'field');
});

test('projects and artifacts have no chat scope', () => {
  assert.equal(resolveScope('projects'), '');
  assert.equal(resolveScope('artifacts'), '');
});

test('scope labels are human readable', () => {
  assert.equal(scopeLabel('project:p1'), 'Project');
  assert.equal(scopeLabel('agent:a1'), 'Agent');
  assert.equal(scopeLabel('field'), 'Knowledge');
  assert.equal(scopeLabel('chat'), 'Chat');
});
