import { execFileSync } from 'node:child_process';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { compile } from 'json-schema-to-typescript';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = fileURLToPath(new URL('../src/generated/', import.meta.url));
const schema = JSON.parse(
  execFileSync('uv', ['run', 'python', 'scripts/export_web_schema.py'], {
    cwd: root,
    encoding: 'utf8',
    maxBuffer: 4 * 1024 * 1024,
  }),
);
const declarations = await compile(schema, 'RuntimeProtocol', {
  bannerComment: '/* Generated from Pydantic serialization schemas. Run npm run schema. */',
  additionalProperties: false,
  style: { singleQuote: true, printWidth: 100 },
});
const files = {
  'protocol.d.ts': declarations,
  'protocol.schema.json': `${JSON.stringify(schema, null, 2)}\n`,
};
if (process.argv.includes('--check')) {
  for (const [name, content] of Object.entries(files)) {
    const current = await readFile(`${output}${name}`, 'utf8').catch(() => '');
    if (current !== content) {
      throw new Error(`Protocol drift in ${name}; run npm --prefix web run schema.`);
    }
  }
  console.log('Generated protocol matches the Python contracts.');
} else {
  await mkdir(output, { recursive: true });
  for (const [name, content] of Object.entries(files)) {
    await writeFile(`${output}${name}`, content);
  }
  console.log('Generated TypeScript and runtime JSON Schema from Python contracts.');
}
