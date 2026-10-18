import { execFile } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import type { TestProject } from 'vitest/node';

export default async function setup(project: TestProject) {
  const directory = await mkdtemp(join(tmpdir(), 'agenttinker-web-oracles-'));
  try {
    for (const [name, script] of [
      ['events', 'export_event_fixtures.py'],
      ['assessments', 'export_assessment_fixtures.py'],
    ]) {
      const { stdout } = await promisify(execFile)('uv', ['run', 'python', `scripts/${script}`], {
        cwd: fileURLToPath(new URL('../../../', import.meta.url)),
        encoding: 'utf8',
        maxBuffer: 4 * 1024 * 1024,
        timeout: 60_000,
      });
      JSON.parse(stdout);
      await writeFile(join(directory, `${name}.json`), stdout);
    }
    project.provide('offlineFixtureDirectory', directory);
    return () => rm(directory, { recursive: true, force: true });
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
}
