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
export type Scenario = RuntimeProtocol['scenarios'][number];
export type DocumentRunRequest = RuntimeProtocol['document_run_request'];
export type EvaluationRequest = RuntimeProtocol['evaluation_request'];
export type ReviewRequest = RuntimeProtocol['review_request'];
export type Evaluation = RuntimeProtocol['evaluation'];
export type HumanReview = RuntimeProtocol['human_review'];
export type EvaluationPage = RuntimeProtocol['evaluation_page'];
export type ReviewPage = RuntimeProtocol['review_page'];

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
