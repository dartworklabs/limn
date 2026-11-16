// The type stripper (tools/strip_types.mjs, docs/adr/0043-viewer-typescript.md): what it takes out and what it refuses, on
// cases of its own, and on every viewer module that it leaves the program TypeScript's own emit leaves.
//
// Run: npm ci --ignore-scripts && npm test
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import ts from 'typescript';
import { listedModules } from '../check_viewer_boundaries.mjs';
import { stripTypes } from '../strip_types.mjs';

const VIEWER = join(import.meta.dirname, '..', '..', 'src', 'limn', 'viewer');

test('types come out and every other byte stays', () => {
  const cases = [
    ['function f(a: number, b?: string): void {}\n', 'function f(a, b) {}\n'],
    ['const g = <T,>(v: T): T => v;\n', 'const g = (v) => v;\n'],
    ['let x: Map<string, number> | null = null;\n', 'let x = null;\n'],
    ['let y!: number;\n', 'let y;\n'],
    ['const a = (b as unknown as HTMLElement).id;\n', 'const a = (b).id;\n'],
    ['const c = d satisfies object;\n', 'const c = d;\n'],
    ['const e = f!.g;\n', 'const e = f.g;\n'],
    ['const h = new Map<string, number>();\n', 'const h = new Map();\n'],
    ['k<number>(1);\n', 'k(1);\n'],
    ['function m(this: Window, n: number) {}\n', 'function m(n) {}\n'],
    ['// note\ntype T = { a: number };\nconst z = 1;\n', '// note\nconst z = 1;\n'],
    ['interface I {\n  a: number;\n}\nconst z = 1;\n', 'const z = 1;\n'],
    ["import type { A } from './a.ts';\nimport { b, type C } from './b.ts';\n", "import { b } from './b.ts';\n"],
    ['export type { T };\nexport { u, type V };\n', 'export { u };\n'],
    ['declare const w: number;\nfunction o(p: number): void;\nfunction o(p) {}\n', 'function o(p) {}\n'],
    [
      'class H implements I {\n  declare text: string;\n  private readonly n?: number = 1;\n}\n',
      'class H {\n  n = 1;\n}\n',
    ],
    [
      '/** A comment. @param a says it */\nfunction q(a: string) {}\n',
      '/** A comment. @param a says it */\nfunction q(a) {}\n',
    ],
    ['const s = `${t as string}`;\n', 'const s = `${t}`;\n'],
  ];
  for (const [ts_, js] of cases) assert.equal(stripTypes(ts_), js, ts_);
});

test('TypeScript that is not only a type is refused, and so is a module that does not parse', () => {
  for (const code of [
    'enum E { A }\n',
    'namespace N {}\n',
    'class C { constructor(private a: number) {} }\n',
    'import x = require("x");\n',
    'export = 1;\n',
    'abstract class A {}\n',
    '@d class D {}\n',
  ]) {
    assert.throws(() => stripTypes(code), /not only a type/, code);
  }
  assert.throws(() => stripTypes('const = 1;\n'), SyntaxError);
});

/** The program of a JavaScript text as TypeScript's parser reads it: every node's kind and every name's and literal's
 * text, in order. Parentheses are not part of it - they group, and the stripper and the emit may leave different ones
 * round an expression whose assertion they took out - and neither are comments or layout. */
function program(code) {
  const sf = ts.createSourceFile('x.js', code, ts.ScriptTarget.ESNext, true, ts.ScriptKind.JS);
  const out = [];
  const walk = (node) => {
    if (node.kind !== ts.SyntaxKind.ParenthesizedExpression) {
      out.push(ts.SyntaxKind[node.kind]);
      if (node.kind <= ts.SyntaxKind.LastToken || ts.isIdentifier(node) || ts.isPrivateIdentifier(node))
        out.push(node.getText(sf));
    }
    ts.forEachChild(node, walk);
  };
  walk(sf);
  return out;
}

test("every viewer module strips to the program TypeScript's own emit gives", () => {
  for (const name of listedModules(VIEWER)) {
    const code = readFileSync(join(VIEWER, name), 'utf8');
    const emitted = ts.transpileModule(code, {
      fileName: name,
      reportDiagnostics: false,
      compilerOptions: {
        target: ts.ScriptTarget.ESNext,
        module: ts.ModuleKind.ESNext,
        verbatimModuleSyntax: true,
        useDefineForClassFields: true,
        removeComments: true,
      },
    }).outputText;
    assert.deepEqual(program(stripTypes(code, name)), program(emitted), name);
  }
});
