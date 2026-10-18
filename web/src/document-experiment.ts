import type { DocumentRunRequest, Run, Scenario } from './protocol';

export function isDocumentRun(run: Run) {
  return (
    run.config.agent.id === 'document-react' &&
    ['1', '2'].includes(run.config.agent.version) &&
    run.config.experiment?.id === 'document-missing' &&
    run.config.experiment.version === run.config.agent.version &&
    run.config.prompt_version === `document-react-v${run.config.agent.version}`
  );
}

export function documentScenario(scenarios: Scenario[], version?: '1' | '2') {
  const find = (requested: string) =>
    scenarios.find(
      (scenario) =>
        scenario.definition.ref.id === 'document-missing' &&
        scenario.definition.ref.version === requested,
    );
  const found = version ? find(version) : (find('2') ?? find('1'));
  if (
    !found ||
    found.agent.ref.id !== 'document-react' ||
    !['1', '2'].includes(found.agent.ref.version) ||
    found.definition.ref.version !== found.agent.ref.version ||
    found.agent.prompt_version !== `document-react-v${found.agent.ref.version}` ||
    found.definition.agent.id !== found.agent.ref.id ||
    found.definition.agent.version !== found.agent.ref.version ||
    found.definition.case.id !== found.case.ref.id ||
    found.definition.case.version !== found.case.ref.version
  )
    throw new Error('protocol_invalid');
  return found;
}

export function documentRequestIdentity(request: DocumentRunRequest) {
  return JSON.stringify([
    request.mode,
    request.provider ?? null,
    request.model ?? null,
    request.variant ?? 'baseline',
    request.agent_version ?? '1',
  ]);
}

export const coverageLabels = {
  covered: '已覆盖',
  missing: '未覆盖',
  uncertain: '不确定',
} as const;
export const judgementLabels = {
  supported: '回答有材料支持',
  justified_insufficiency: '材料不足，回答如实说明',
  unsupported: '包含材料不支持的断言',
  uncertain: '尚无法判断',
} as const;
