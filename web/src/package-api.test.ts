import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { exportPackage, getProvenance, importPackage } from './api';
import { parseProtocol, type ImportProvenance, type ImportResult } from './protocol';
import { actionError } from './mutations';

let fixture: { package: unknown; import_result: ImportResult; import_provenance: ImportProvenance };
beforeAll(() => {
  fixture = JSON.parse(
    execFileSync('uv', ['run', 'python', 'scripts/export_assessment_fixtures.py'], {
      cwd: fileURLToPath(new URL('../../', import.meta.url)),
      encoding: 'utf8',
      maxBuffer: 4 * 1024 * 1024,
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

it('uploads exact file bytes under an explicit durable key and validates the Python receipt', async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json(fixture.import_result));
  vi.stubGlobal('fetch', fetcher);
  const bytes = new TextEncoder().encode(JSON.stringify(fixture.package));
  expect(await importPackage(bytes, 'file-key')).toEqual(fixture.import_result);
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe('/api/v1/imports');
  expect(options.body).toBe(bytes);
  expect(options.headers['Idempotency-Key']).toBe('file-key');
  expect(options.headers['Content-Type']).toBe('application/json');
});

it('rejects a receipt without its root or with duplicate local identities', async () => {
  for (const changed of [
    { ...fixture.import_result, root_run_id: 'foreign' },
    {
      ...fixture.import_result,
      runs: [...fixture.import_result.runs, fixture.import_result.runs[0]],
    },
  ]) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(changed)));
    await expect(importPackage(new Uint8Array(), 'file-key')).rejects.toThrow('protocol_invalid');
  }
});

it('keeps source opinions and both evidence digests under their original identities', async () => {
  const source = fixture.import_provenance;
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => Response.json(source)),
  );
  expect(await getProvenance(source.local_run_id)).toEqual(source);
  expect(source.claim).toBe('unverified_source_record');
  expect(source.source_mode).toBe('synthetic');
  expect(source.evaluations[0].run_id).toBe(source.source_run_id);
  expect(source.evaluation_bindings[0].source_input_hash).toBe(source.evaluations[0].input_hash);
  expect(source.evaluation_bindings[0].portable_input_hash).not.toBe(
    source.evaluations[0].input_hash,
  );
  await expect(getProvenance('foreign')).rejects.toThrow('protocol_invalid');
  expect(() => parseProtocol('import_provenance', { ...source, claim: 'verified_live' })).toThrow(
    'protocol_invalid',
  );
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(null)));
  expect(await getProvenance('native')).toBeNull();
});

it('downloads JSON bytes and uses only safe stable package error messages', async () => {
  const bytes = JSON.stringify(fixture.package);
  const fetcher = vi.fn().mockResolvedValue(new Response(bytes));
  vi.stubGlobal('fetch', fetcher);
  expect(await (await exportPackage('id:one')).text()).toBe(bytes);
  expect(fetcher.mock.calls[0][0]).toBe('/api/v1/runs/id%3Aone/export');
  for (const code of ['package_invalid', 'package_too_large', 'artifact_contains_credentials']) {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(Response.json({ detail: code }, { status: 422 })),
    );
    await expect(importPackage(new Uint8Array(), 'key')).rejects.toThrow(code);
    expect(actionError(new Error(code))).not.toContain('未能确认');
  }
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(Response.json({ detail: 'private-error-marker' }, { status: 500 })),
  );
  await expect(exportPackage('native')).rejects.not.toThrow('private-error-marker');
});
