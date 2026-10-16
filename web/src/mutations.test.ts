import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { actionError, forgetIntent, pendingIntent, rememberIntent } from './mutations';

let storage: Map<string, string>;
beforeEach(() => {
  storage = new Map();
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

it('retains the same durable key for a retry after a lost response or reload', () => {
  const body = { mode: 'synthetic', policy: { top_k: 2, tool_retry_limit: 0 } };
  const first = rememberIntent('create', body);
  expect(pendingIntent('create')).toEqual(first);
  expect(rememberIntent('create', { policy: body.policy, mode: body.mode })).toEqual(first);
  expect(rememberIntent('create', { ...body, mode: 'live' }).key).not.toBe(first.key);
  // Returning to a previously uncertain payload must still reuse its old key.
  expect(rememberIntent('create', body).key).toBe(first.key);
});

it('isolates fork scopes and clears only the acknowledged intent', () => {
  const a = rememberIntent('create', { task: 'A' });
  const b = rememberIntent('fork:A:cp', { patch: { top_k: 3 } });
  forgetIntent(b.key);
  expect(pendingIntent('fork:A:cp')).toBeNull();
  expect(pendingIntent('create')).toEqual(a);
  forgetIntent(a.key);
  expect(pendingIntent('create')).toBeNull();
});

it('does not invent a replacement identity when pending request storage is unreadable', () => {
  storage.set('agenttinker.pending-requests.v1', '{broken');
  expect(() => rememberIntent('create', {})).toThrow('request_memory_unavailable');
});

it('never displays raw exception or provider text in operation feedback', () => {
  expect(actionError(new Error('private-provider-marker'))).not.toContain(
    'private-provider-marker',
  );
  expect(actionError(new Error('provider_not_configured'))).toContain('真实模型尚未配置');
});
