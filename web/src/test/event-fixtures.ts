import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import type { RuntimeEvent, RunView } from '../protocol';

type Example = { events: RuntimeEvent[]; prefixes: RunView[]; view: RunView };

export function eventFixtures(): Record<
  | 'failed'
  | 'retried'
  | 'cancelled'
  | 'forked'
  | 'document'
  | 'document_forked'
  | 'imported'
  | 'document_v2'
  | 'document_v2_forked'
  | 'imported_v2',
  Example
> {
  return JSON.parse(
    execFileSync('uv', ['run', 'python', 'scripts/export_event_fixtures.py'], {
      cwd: fileURLToPath(new URL('../../../', import.meta.url)),
      encoding: 'utf8',
      maxBuffer: 4 * 1024 * 1024,
    }),
  );
}
