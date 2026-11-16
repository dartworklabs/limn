// One-off migration (docs/adr/0042-viewer-es-modules.md): turns the viewer's classic-script parts into ES modules, in place.
//
// Each part listed under __APP_JS__ in parts.txt is parsed as a script and scope-analysed (acorn, eslint-scope). A name
// a part declares at its top level belongs to that part; every reference another part makes to it becomes a named
// import, and the owner exports exactly the names other parts use. A write to another part's binding (`X=v`, `X+=v`,
// `++X`, `X++` as a statement) becomes a call of a setter the owner declares (`setX(v)`, which answers v, so a write used
// as a value keeps its value); any other form of such a write stops the tool. Nothing else in a part changes: the code
// between the imports at the top and the setters and export list at the end is the part's text, write sites aside.
// core.js loses its 'use strict' directive (modules are strict; the build puts it back at the top of the script).
//
// It ran once, on the parts as they were at 79115287, and is kept for review in the commit that ran it; the modules it
// wrote are the source from then on, and the tool is removed after (it reads classic scripts, which no longer exist).
//
// Run: from a folder where acorn@8.15.0 and eslint-scope@8.4.0 are installed (npm i them there, copy this file in):
//      node viewer_modules_codemod.mjs <checkout>/src/limn/viewer
import fs from 'node:fs';
import path from 'node:path';
import * as acorn from 'acorn';
import * as eslintScope from 'eslint-scope';

const [root] = process.argv.slice(2);
const outDir = root;
const manifest = fs.readFileSync(path.join(root, 'parts.txt'), 'utf8').split('\n');
const parts = [];
let inJs = false;
for (const raw of manifest) {
  const line = raw.split('#')[0].trim();
  if (!line) continue;
  if (line === '__APP_JS__') { inJs = true; continue; }
  if (line.startsWith('__')) { inJs = false; continue; }
  if (inJs) parts.push(line);
}
const files = parts.map((p, i) => {
  const src = fs.readFileSync(path.join(root, p), 'utf8');
  const ast = acorn.parse(src, { ecmaVersion: 2024, sourceType: 'script', ranges: true, locations: true });
  const sm = eslintScope.analyze(ast, { ecmaVersion: 2024, sourceType: 'script', childVisitorKeys: undefined });
  return { p, i, src, ast, sm, gs: sm.globalScope, base: path.basename(p) };
});
const owner = new Map();
for (const f of files) for (const v of f.gs.variables) owner.set(v.name, f.i);

const pascal = n => n.toLowerCase().split('_').filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join('');
const setterOf = new Map(); // name -> setter name
const allNames = new Set(owner.keys());
// pass 1: references
const uses = files.map(() => new Map()); // file -> owner index -> Set(names read or written)
const writes = files.map(() => []);      // file -> [{name, ref}]
const writtenElsewhere = files.map(() => new Set()); // owner file -> names written by other files
for (const f of files) {
  for (const s of f.sm.scopes) for (const r of s.references) {
    const name = r.identifier.name;
    if (!owner.has(name)) continue;
    if (r.resolved && r.resolved.scope.type !== 'global') continue;
    const o = owner.get(name);
    if (o === f.i) continue;
    if (!uses[f.i].has(o)) uses[f.i].set(o, new Set());
    if (r.isWrite()) {
      writes[f.i].push({ name, r });
      writtenElsewhere[o].add(name);
    }
    if (r.isRead() || !r.isWrite()) uses[f.i].get(o).add(name);
    if (r.isReadWrite()) uses[f.i].get(o).add(name);
  }
}
for (const [i, names] of writtenElsewhere.entries()) for (const n of names) {
  let s = 'set' + pascal(n);
  if (allNames.has(s) || [...allNames].some(x => x.toLowerCase() === s.toLowerCase())) s += 'State';
  if (allNames.has(s)) throw new Error('setter collision ' + s);
  setterOf.set(n, s); allNames.add(s);
}
for (const f of files) for (const w of writes[f.i]) uses[f.i].get(owner.get(w.name)).add(setterOf.get(w.name));
// drop names only written (never read) from the import of the name itself
for (const f of files) {
  for (const [o, names] of uses[f.i]) {
    for (const n of [...names]) {
      if (!setterOf.has(n) || setterOf.get(n) === n) continue;
      const reads = f.sm.scopes.some(s => s.references.some(r => r.identifier.name === n && (!r.resolved || r.resolved.scope.type === 'global') && r.isRead()));
      if (!reads) names.delete(n);
    }
  }
}

// parent links
function parents(ast) {
  const map = new Map();
  (function visit(node, parent) {
    if (!node || typeof node.type !== 'string') return;
    map.set(node, parent);
    for (const k of Object.keys(node)) {
      if (k === 'parent') continue;
      const v = node[k];
      if (Array.isArray(v)) v.forEach(c => c && typeof c.type === 'string' && visit(c, node));
      else if (v && typeof v.type === 'string') visit(v, node);
    }
  })(ast, null);
  return map;
}

function rewrite(f) {
  const par = parents(f.ast);
  const edits = []; // {start, end, render: (sub) => string}
  for (const w of writes[f.i]) {
    const id = w.r.identifier, p = par.get(id), set = setterOf.get(w.name);
    if (p.type === 'AssignmentExpression' && p.left === id) {
      if (p.operator === '=') edits.push({ start: p.start, end: p.end, render: sub => `${set}(${sub(p.right)})` });
      else if (['||=', '&&=', '??='].includes(p.operator)) {
        const op = p.operator.slice(0, 2);
        edits.push({ start: p.start, end: p.end, render: sub => `(${w.name}${op}${set}(${sub(p.right)}))` });
      } else {
        const op = p.operator.slice(0, -1);
        edits.push({ start: p.start, end: p.end, render: sub => `${set}(${w.name}${op}(${sub(p.right)}))` });
      }
    } else if (p.type === 'UpdateExpression') {
      const op = p.operator[0];
      const gp = par.get(p);
      if (!p.prefix && !(gp.type === 'ExpressionStatement' || (gp.type === 'SequenceExpression' && par.get(gp).type === 'ExpressionStatement'))) {
        throw new Error(`${f.p}: postfix update with its value used: ${f.src.slice(gp.start, gp.end)}`);
      }
      edits.push({ start: p.start, end: p.end, render: () => `${set}(${w.name}${op}1)` });
    } else {
      throw new Error(`${f.p}: unsupported write of ${w.name}: ${f.src.slice(p.start, p.end)}`);
    }
  }
  edits.sort((a, b) => a.start - b.start || b.end - a.end);
  function text(start, end) {
    let out = '', at = start;
    for (const e of edits) {
      if (e.start < at || e.end > end) continue; // nested in an earlier edit or outside
      if (e.start < start) continue;
      out += f.src.slice(at, e.start) + e.render(node => text(node.start, node.end));
      at = e.end;
    }
    return out + f.src.slice(at, end);
  }
  let body = text(0, f.src.length);
  return body;
}

function wrapList(prefix, names, suffix) {
  const lines = []; let cur = prefix;
  names.forEach((n, k) => {
    const piece = n + (k < names.length - 1 ? ',' : '');
    if (cur.length + piece.length + 1 + (k === names.length - 1 ? suffix.length : 0) > 120 && cur !== prefix) { lines.push(cur.trimEnd()); cur = '  '; }
    cur += piece + (k < names.length - 1 ? ' ' : '');
  });
  lines.push(cur + suffix);
  return lines.join('\n');
}

for (const f of files) {
  let body = rewrite(f);
  if (f.i === 0) body = body.replace(/^'use strict';\n/, '');
  // exports: names other files use, plus setters
  const exp = new Set();
  for (const g of files) for (const [o, names] of uses[g.i]) if (o === f.i) for (const n of names) if (owner.get(n) === f.i) exp.add(n);
  const setters = [...writtenElsewhere[f.i]].sort();
  const setterSrc = setters.map(n => `// Sets ${n}, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.\n/** @template {typeof ${n}} T @param {T} v @returns {T} */\nfunction ${setterOf.get(n)}(v){${n}=v; return v;}`).join('\n');
  setters.forEach(n => exp.add(setterOf.get(n)));
  // imports
  const imps = [];
  for (const [o, names] of [...uses[f.i]].sort((a, b) => a[0] - b[0])) {
    const list = [...names].sort();
    if (list.length) imps.push(wrapList('import { ', list, ` } from './${files[o].base}';`));
  }
  // insert imports after the leading comment block
  const lines = body.split('\n'); let k = 0;
  while (k < lines.length && lines[k].startsWith('//')) k++;
  const head = lines.slice(0, k), rest = lines.slice(k);
  let out = [...head, ...imps, ...rest].join('\n');
  if (!out.endsWith('\n')) out += '\n';
  if (setterSrc) out += setterSrc + '\n';
  const expList = [...exp].sort();
  if (expList.length) out += wrapList('export { ', expList, ' };') + '\n';
  fs.mkdirSync(path.join(outDir, path.dirname(f.p)), { recursive: true });
  fs.writeFileSync(path.join(outDir, f.p), out);
}
console.log('setters', setterOf.size);
