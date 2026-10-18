import type { RuntimeEvent, RunView } from '../protocol';
import { offlineFixture } from './offline-fixtures';

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
  return offlineFixture('events');
}
