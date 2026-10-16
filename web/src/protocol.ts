import Ajv from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import type { RuntimeProtocol } from './generated/protocol';
import schema from './generated/protocol.schema.json';

export type RunView = RuntimeProtocol['run_view'];
export type RunPage = RuntimeProtocol['run_page'];
export type RuntimeEvent = RuntimeProtocol['event'];
export type Run = RunView['run'];
export type Span = RunView['spans'][number];
export type Checkpoint = RunView['checkpoints'][number];
export type RunRequest = RuntimeProtocol['run_request'];
export type ForkRequest = RuntimeProtocol['fork_request'];
export type CheckpointAvailability = RuntimeProtocol['checkpoint_availability'][number];

const ajv = new Ajv({ strict: false, allErrors: false });
addFormats(ajv);

const validators = Object.fromEntries(
  Object.entries(schema.properties).map(([name, definition]) => [
    name,
    ajv.compile({ ...definition, $defs: schema.$defs }),
  ]),
);

export function parseProtocol<K extends keyof RuntimeProtocol>(
  name: K,
  value: unknown,
): RuntimeProtocol[K] {
  if (!validators[name](value)) throw new Error('protocol_invalid');
  return value as RuntimeProtocol[K];
}
