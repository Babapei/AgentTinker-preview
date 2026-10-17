import type { Run, Scenario } from './protocol';

export function isDocumentRun(run: Run) {
  return (
    run.config.agent.id === 'document-react' &&
    run.config.agent.version === '1' &&
    run.config.experiment?.id === 'document-missing' &&
    run.config.experiment.version === '1'
  );
}

export function documentScenario(scenarios: Scenario[]) {
  const found = scenarios.find(
    (scenario) =>
      scenario.definition.ref.id === 'document-missing' && scenario.definition.ref.version === '1',
  );
  if (
    !found ||
    found.agent.ref.id !== 'document-react' ||
    found.agent.ref.version !== '1' ||
    found.definition.agent.id !== found.agent.ref.id ||
    found.definition.agent.version !== found.agent.ref.version ||
    found.definition.case.id !== found.case.ref.id ||
    found.definition.case.version !== found.case.ref.version
  )
    throw new Error('protocol_invalid');
  return found;
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
