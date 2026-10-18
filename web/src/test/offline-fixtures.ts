import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { inject } from 'vitest';

declare module 'vitest' {
  export interface ProvidedContext {
    offlineFixtureDirectory: string;
  }
}

export function offlineFixture(name: 'events' | 'assessments') {
  return JSON.parse(readFileSync(join(inject('offlineFixtureDirectory'), `${name}.json`), 'utf8'));
}
