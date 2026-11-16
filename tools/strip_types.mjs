// Takes the TypeScript types out of a viewer module, leaving the JavaScript the browser runs (docs/adr/0043-viewer-typescript.md,
// docs/handbook/viewer.md §뷰어 규칙을 바꿀 때).
//
// The viewer's modules are TypeScript written in its erasable subset only (tsconfig.json: erasableSyntaxOnly,
// verbatimModuleSyntax): every piece of TypeScript in them is a type that can be deleted with nothing put in its place.
// This deletes exactly those pieces and keeps every other byte - code, comments and layout - as written, so the module's
// code reads in the built script as it reads in the module, without its types. It is not a compiler: it does not
// downlevel, rename or reprint, and it refuses (throws) the TypeScript that is not only a type - enum, namespace, a
// parameter property, a decorator, `import x = require()`, `export =`, abstract - and a module that does not parse.
//
// What it deletes: type annotations (`: T` of a parameter, variable, property or return), the `?` of an optional
// parameter or property and the `!` of a definite assignment, type parameters and type arguments (`<T>`), `as T`,
// `satisfies T`, `<T>x` and the non-null `x!`, `this` parameters, `implements` clauses, the modifiers public, private,
// protected, readonly and override, and whole statements that are only types: type aliases, interfaces, `declare`
// statements and fields, overload signatures, index signatures, `import type` and `export type`, and the `type`
// specifiers of an import or export list. A deleted statement takes its line with it when it had the line to itself;
// its leading comment stays.
//
// The parser is TypeScript's own, the exact version package-lock.json pins for typescript-eslint, so the output is the
// same on every machine. tools/tests/strip_types.test.mjs checks the output against TypeScript's own emit on every
// viewer module.
//
// Run: node tools/strip_types.mjs <file>...   (prints {"<file>": "<its code>", ...} as JSON)
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const K = ts.SyntaxKind;
// Modifiers that only say something to the type checker.
const TYPE_MODIFIERS = new Set([
  K.PublicKeyword,
  K.PrivateKeyword,
  K.ProtectedKeyword,
  K.ReadonlyKeyword,
  K.OverrideKeyword,
]);

/**
 * The module's code with its types taken out. Throws on a parse error or on TypeScript that is not erasable.
 * @param {string} code the module's text
 * @param {string} [fileName] the name errors say
 * @returns {string}
 */
export function stripTypes(code, fileName = 'module.ts') {
  const sf = ts.createSourceFile(fileName, code, ts.ScriptTarget.ESNext, true, ts.ScriptKind.TS);
  const where = (/** @type {number} */ at) => {
    const { line, character } = sf.getLineAndCharacterOfPosition(at);
    return `${fileName}:${line + 1}:${character + 1}`;
  };
  // parseDiagnostics is not in TypeScript's declared API, but it is where a syntax error is reported without a program.
  for (const d of /** @type {any} */ (sf).parseDiagnostics || []) {
    throw new SyntaxError(`${where(d.start)}: ${ts.flattenDiagnosticMessageText(d.messageText, '\n')}`);
  }
  /** @type {[number, number][]} */
  const cuts = [];
  const refuse = (/** @type {ts.Node} */ node, /** @type {string} */ what) => {
    throw new Error(`${where(node.getStart(sf))}: ${what} is TypeScript that is not only a type (erasableSyntaxOnly)`);
  };
  const isSpace = (/** @type {string} */ c) => c === ' ' || c === '\t';
  // The offset of the first character that is not white space at or after i (or before i, going back).
  const skipForward = (/** @type {number} */ i) => {
    while (i < code.length && /\s/.test(code[i])) i++;
    return i;
  };
  const skipBack = (/** @type {number} */ i) => {
    while (i > 0 && /\s/.test(code[i - 1])) i--;
    return i;
  };
  const expect = (/** @type {number} */ at, /** @type {string} */ ch) => {
    if (code[at] !== ch) throw new Error(`${where(at)}: expected ${ch} here (the type stripper lost its place)`);
    return at;
  };
  const cut = (/** @type {number} */ start, /** @type {number} */ end) => {
    if (end > start) cuts.push([start, end]);
  };
  // `: T` after a name, a `?`, or a parameter list's `)`: from the colon (and any space before it) to the type's end.
  const cutAnnotation = (/** @type {ts.TypeNode} */ type) => {
    const colon = expect(skipBack(type.getStart(sf)) - 1, ':');
    cut(skipBack(colon), type.end);
  };
  // `<...>` round a list of type parameters or arguments.
  const cutAngles = (/** @type {ts.NodeArray<ts.Node>} */ list) => {
    const open = expect(skipBack(list[0].getStart(sf)) - 1, '<');
    let close = list.end;
    while (/[\s,]/.test(code[close])) close++;
    expect(close, '>');
    cut(open, close + 1);
  };
  // A whole statement or class member, with its line when it had the line to itself. Its leading comments stay.
  const cutStatement = (/** @type {ts.Node} */ node) => {
    let start = node.getStart(sf),
      end = node.end;
    let a = start;
    while (a > 0 && isSpace(code[a - 1])) a--;
    let b = end;
    while (b < code.length && isSpace(code[b])) b++;
    if ((a === 0 || code[a - 1] === '\n') && (b === code.length || code[b] === '\n')) {
      start = a;
      end = Math.min(b + 1, code.length);
    }
    cut(start, end);
  };
  // One item of a comma-separated list (a `this` parameter, a `type` specifier), with the comma that goes with it.
  const cutListItem = (/** @type {ts.Node} */ node) => {
    const start = node.getStart(sf);
    const after = skipForward(node.end);
    if (code[after] === ',') cut(start, skipForward(after + 1));
    else {
      const before = skipBack(start) - 1;
      cut(code[before] === ',' ? before : start, node.end);
    }
  };
  const cutModifiers = (/** @type {ts.Node} */ node) => {
    for (const m of ts.canHaveModifiers(node) ? ts.getModifiers(node) || [] : []) {
      if (m.kind === K.AbstractKeyword) refuse(m, 'abstract');
      if (TYPE_MODIFIERS.has(m.kind)) cut(m.getStart(sf), skipForward(m.end));
    }
  };
  const declared = (/** @type {ts.Node} */ node) =>
    ts.canHaveModifiers(node) && (ts.getModifiers(node) || []).some((m) => m.kind === K.DeclareKeyword);

  /** @param {ts.Node} node */
  const visit = (node) => {
    if (ts.canHaveDecorators(node) && ts.getDecorators(node)?.length) refuse(node, 'a decorator');
    if (declared(node)) return cutStatement(node);
    switch (node.kind) {
      case K.InterfaceDeclaration:
      case K.TypeAliasDeclaration:
      case K.IndexSignature:
        return cutStatement(node);
      case K.EnumDeclaration:
        return refuse(node, 'an enum');
      case K.ModuleDeclaration:
        return refuse(node, 'a namespace');
      case K.ImportEqualsDeclaration:
        return /** @type {ts.ImportEqualsDeclaration} */ (node).isTypeOnly
          ? cutStatement(node)
          : refuse(node, 'import =');
      case K.ExportAssignment:
        if (/** @type {ts.ExportAssignment} */ (node).isExportEquals) refuse(node, 'export =');
        break;
      case K.ImportDeclaration: {
        const clause = /** @type {ts.ImportDeclaration} */ (node).importClause;
        if (clause?.isTypeOnly) return cutStatement(node);
        break;
      }
      case K.ExportDeclaration:
        if (/** @type {ts.ExportDeclaration} */ (node).isTypeOnly) return cutStatement(node);
        break;
      case K.ImportSpecifier:
      case K.ExportSpecifier:
        if (/** @type {ts.ImportSpecifier | ts.ExportSpecifier} */ (node).isTypeOnly) return cutListItem(node);
        return;
      case K.FunctionDeclaration:
      case K.MethodDeclaration:
      case K.Constructor:
        if (!(/** @type {ts.FunctionLikeDeclaration} */ (node).body)) return cutStatement(node); // an overload
        break;
      case K.Parameter: {
        const p = /** @type {ts.ParameterDeclaration} */ (node);
        if (ts.isIdentifier(p.name) && p.name.text === 'this') return cutListItem(node);
        if ((ts.getModifiers(p) || []).length) refuse(node, 'a parameter property');
        if (p.questionToken) cut(p.questionToken.getStart(sf), p.questionToken.end);
        break;
      }
      case K.PropertyDeclaration: {
        const p = /** @type {ts.PropertyDeclaration} */ (node);
        const mark = p.questionToken || p.exclamationToken;
        if (mark) cut(mark.getStart(sf), mark.end);
        break;
      }
      case K.VariableDeclaration: {
        const v = /** @type {ts.VariableDeclaration} */ (node);
        if (v.exclamationToken) cut(v.exclamationToken.getStart(sf), v.exclamationToken.end);
        break;
      }
      case K.HeritageClause:
        if (/** @type {ts.HeritageClause} */ (node).token === K.ImplementsKeyword)
          return cut(skipBack(node.getStart(sf)), node.end);
        break;
      case K.AsExpression:
      case K.SatisfiesExpression:
      case K.NonNullExpression: {
        const e = /** @type {ts.AsExpression | ts.SatisfiesExpression | ts.NonNullExpression} */ (node);
        cut(e.expression.end, node.end);
        return visit(e.expression);
      }
      case K.TypeAssertionExpression: {
        const e = /** @type {ts.TypeAssertion} */ (node);
        cut(node.getStart(sf), e.expression.getStart(sf));
        return visit(e.expression);
      }
      default:
        break;
    }
    cutModifiers(node);
    const n = /** @type {any} */ (node);
    if (n.typeParameters?.length) cutAngles(n.typeParameters);
    if (n.typeArguments?.length) cutAngles(n.typeArguments);
    if (n.type && ts.isTypeNode(n.type) && !ts.isTypeNode(node)) cutAnnotation(n.type);
    ts.forEachChild(node, (child) => {
      if (!ts.isTypeNode(child) || ts.isExpressionWithTypeArguments(child)) visit(child);
    });
  };
  ts.forEachChild(sf, visit);

  cuts.sort((a, b) => a[0] - b[0]);
  let out = '',
    at = 0;
  for (const [start, end] of cuts) {
    if (start < at) throw new Error(`${where(start)}: two type cuts overlap (the type stripper lost its place)`);
    out += code.slice(at, start);
    at = end;
  }
  return out + code.slice(at);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  /** @type {Record<string, string>} */
  const out = {};
  for (const file of process.argv.slice(2)) out[file] = stripTypes(readFileSync(file, 'utf8'), file);
  process.stdout.write(JSON.stringify(out));
}
