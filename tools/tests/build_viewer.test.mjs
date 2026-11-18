import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { build } from '../build_viewer.mjs';

/** An independent viewer with the same entry point and no source list. */
function viewerFixture(t, sources) {
  const viewer = mkdtempSync(join(tmpdir(), 'limn-build-'));
  t.after(() => rmSync(viewer, { recursive: true, force: true }));
  for (const [name, source] of Object.entries(sources)) {
    const file = join(viewer, 'js', name);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, source);
  }
  return viewer;
}

test('the classic script evaluates a shared dependency once and side effects in import order before boot', async (t) => {
  const viewer = viewerFixture(t, {
    'main.ts': "import './z.ts';\nimport './b.ts';\nimport { value } from './a.ts';\nrecord(value);",
    'b.ts': "record('second listener');",
    'z.ts': "import { value } from './a.ts';\nrecord('listener ' + value);",
    'a.ts': "const value: number = 7;\nrecord('setup');\nexport { value };",
  });
  const events = [];
  const script = await build(viewer);
  assert.ok(script.startsWith("'use strict';"));
  runInNewContext(script, { record: (event) => events.push(event) });
  assert.deepEqual(events, ['setup', 'listener 7', 'second listener', 7]);
});

test('a type import and a disconnected chain cannot hide orphan modules from the build', async (t) => {
  const viewer = viewerFixture(t, {
    'main.ts': "import type { Item } from './unused/state.ts';\nboot();",
    'unused/input.ts': "import './state.ts';\nlisten();",
    'unused/state.ts': 'export type Item = string;\ninitialize();',
  });
  await assert.rejects(build(viewer), /unreachable from js\/main\.ts: js\/unused\/input\.ts, js\/unused\/state\.ts/);
});

test('the classic script cannot export an entry point binding', async (t) => {
  const viewer = viewerFixture(t, { 'main.ts': 'export const value = 1;' });
  await assert.rejects(build(viewer), /would not run as a classic script/);
});
