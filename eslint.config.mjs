// ESLint for the viewer's TypeScript modules (docs/adr/0042-viewer-es-modules.md D7, docs/adr/0043-viewer-typescript.md,
// docs/handbook/viewer.md §타입 검사).
//
// Every rule here is a gate: tools/strict_ratchet.py runs ESLint and holds each file's count per rule to
// tools/strict-baseline.json, which only goes down - a file with more than its baseline fails, and so does one with
// fewer until the baseline is lowered. A file or rule the baseline does not name must have none. `npm run lint` shows
// the messages themselves.
//
// The rules are type-aware: typescript-eslint reads tsconfig.json, the types tsc infers with its strict set (under
// noImplicitAny an unannotated `let x;` or `[]` takes the type its assignments give it), so a value of type any is found whether it
// came from an annotation, an untyped library or a JSON.parse. The escape hatches are typescript-eslint's rules: an
// explicit any, a type assertion (`x as T`, `<T>x`), a non-null assertion (`x!`) and a @ts- directive. Two checks no
// plugin makes are local rules (limnRules below): a write through another module's binding, and a JSDoc type, which
// TypeScript does not read in a .ts file at all. A third, also local, finds a DOM query whose element class TypeScript
// inferred from where its answer goes. Two more local rules keep the code readable
// (docs/adr/0044-viewer-name-and-comment-gates.md): a declared name is whole words, and a comment carries no history.
import globals from 'globals';
import tseslint from 'typescript-eslint';
import { historyIn, loadNameLists, nameProblems } from './tools/viewer_naming.mjs';

/** @typedef {import('eslint').Rule.RuleModule} RuleModule */

/**
 * The type expressions of a JSDoc comment's tags: the text inside each `{...}` after a tag, braces balanced.
 * @param {string} text the comment's text, without its delimiters
 * @returns {string[]}
 */
function jsdocTypes(text) {
  const out = [];
  for (const m of text.matchAll(/@\w+\s*\{/g)) {
    let depth = 1,
      i = m.index + m[0].length;
    const start = i;
    for (; i < text.length && depth; i++) {
      if (text[i] === '{') depth++;
      else if (text[i] === '}') depth--;
    }
    out.push(text.slice(start, i - 1));
  }
  return out;
}

// The TypeScript nodes that wrap a value in a type and nothing else.
const UNWRAP = new Set(['TSAsExpression', 'TSNonNullExpression', 'TSSatisfiesExpression', 'TSTypeAssertion']);

// The DOM queries whose generic overload can take its class from the receiving type (no-inferred-query-class).
const QUERY_NAMES = new Set(['querySelector', 'querySelectorAll', 'closest']);

/** @type {Record<string, RuleModule>} */
export const limnRules = {
  // A JSDoc type in a .ts file: TypeScript reads types only from the code there, so `@param {T}`, `@type {T}`,
  // `@returns {T}`, `@typedef` or `@template` says a type nothing checks. Write it in the code; keep the words.
  'no-jsdoc-type': {
    meta: {
      type: 'problem',
      messages: { type: 'TypeScript does not read a JSDoc type in a .ts file: write the type in the code.' },
      schema: [],
    },
    create(context) {
      return {
        Program() {
          for (const c of context.sourceCode.getAllComments()) {
            if (c.type !== 'Block' || !c.value.startsWith('*')) continue;
            if (jsdocTypes(c.value).length || /@(typedef|template|callback)\b/.test(c.value))
              context.report({ loc: c.loc, messageId: 'type' });
          }
        },
      };
    },
  },
  // A declared name is whole words (docs/handbook/viewer.md §이름과 주석): the words of `pvPress`, `PV_BUSY` or `c` are
  // split off (camelCase, PascalCase, UPPER_SNAKE, digits) and each must be at least three letters, or on the short-word
  // allow-list, and not on the deny list of known abbreviations (tools/viewer-names.json). It reports the declaration -
  // a variable, function, parameter, class, type, type parameter or an import's own alias - once, never its uses, a
  // property name or an object key, and an import that keeps the exporter's name (the exporter is where it is reported).
  'plain-names': {
    meta: {
      type: 'suggestion',
      messages: { name: '{{name}} is not whole words - {{problems}} (tools/viewer-names.json).' },
      schema: [],
    },
    create(context) {
      const lists = loadNameLists();
      if (context.filename.endsWith('.d.ts')) return {}; // ambient declarations mirror the server's own field names
      /** @param {any} def @returns {boolean} */
      const isLoopIndex = (def) => {
        const declaration = def.type === 'Variable' ? def.parent : null;
        const loop = declaration && declaration.parent;
        if (!loop) return false;
        return (
          (loop.type === 'ForStatement' && loop.init === declaration) ||
          ((loop.type === 'ForInStatement' || loop.type === 'ForOfStatement') && loop.left === declaration)
        );
      };
      return {
        Program() {
          /** @type {Set<unknown>} */
          const seen = new Set();
          for (const scope of context.sourceCode.scopeManager.scopes) {
            for (const variable of scope.variables) {
              const def = variable.defs[0];
              if (!def || !def.name || seen.has(def.name)) continue;
              seen.add(def.name);
              // `import { a } from` names a binding the exporting module declares and is reported there; an alias
              // (`import { a as b }`), a default or a namespace import names a new one.
              if (def.node.type === 'ImportSpecifier' && def.node.imported.name === def.name.name) continue;
              const problems = nameProblems(def.name.name, lists, isLoopIndex(def));
              if (problems.length)
                context.report({
                  node: def.name,
                  messageId: 'name',
                  data: { name: def.name.name, problems: problems.join('; ') },
                });
            }
          }
        },
      };
    },
  },
  // A comment says what the code does and why, not how it came to be: a release number (0.4.34), an issue or pull
  // request number (#418, issue #12) or a dated QA note (2026-09-24) belongs to the pull request and the CHANGELOG.
  // One report per comment. A reference to an ADR or the Handbook points at a rule that holds now and is fine, as is
  // an example in quotes ('#12') and an address or specification number (127.0.0.1, WCAG 3.2.2); see historyIn.
  'no-history-comment': {
    meta: {
      type: 'suggestion',
      messages: {
        history:
          'A comment carries no history ({{found}}): say what the code does now; the pull request and the CHANGELOG keep the rest.',
      },
      schema: [],
    },
    create(context) {
      return {
        Program() {
          // A run of `//` lines is read as one text so a quote that spans lines is seen whole; each line is still
          // judged, and reported, on its own.
          const comments = context.sourceCode.getAllComments();
          for (let first = 0; first < comments.length;) {
            let last = first;
            while (
              comments[first].type === 'Line' &&
              last + 1 < comments.length &&
              comments[last + 1].type === 'Line' &&
              comments[last + 1].loc.start.line === comments[last].loc.end.line + 1
            )
              last++;
            const run = comments.slice(first, last + 1);
            const text = run.map((c) => c.value).join('\n');
            let from = 0;
            for (const comment of run) {
              const found = historyIn(text, from, from + comment.value.length + 1);
              from += comment.value.length + 1;
              if (found.length)
                context.report({
                  loc: comment.loc,
                  messageId: 'history',
                  data: { found: found.map((h) => `${h.kind} ${h.text}`).join(', ') },
                });
            }
            first = last + 1;
          }
        },
      };
    },
  },
  // A DOM query whose element class TypeScript took from where its answer goes: querySelector, querySelectorAll and
  // closest with a selector string have a generic overload (`<E extends Element = Element>`), and passing the call
  // straight to a parameter typed `HTMLElement | null` infers E from that parameter - the class said without a check,
  // as a type argument says it (UNCHECKED_QUERIES), but in no syntax a selector can see. A query names its class by
  // checking it (findElement, findMaybe, findAll, findClosest in js/platform/dom.ts); its own answer is Element. A tag
  // name (`querySelector('a')`) takes the tag's overload, which the DOM types by the tag, and passes.
  'no-inferred-query-class': {
    meta: {
      type: 'problem',
      messages: {
        inferred:
          '{{name}} answers {{found}} here only because TypeScript took the class from where the answer goes: check it with findElement, findMaybe, findAll or findClosest (js/platform/dom.ts).',
      },
      schema: [],
    },
    create(context) {
      const services = context.sourceCode.parserServices;
      if (!services || !services.program) return {};
      const checker = services.program.getTypeChecker();
      /** The element class a query's answer holds: E of E | null, or of NodeListOf<E>. @param {any} answer */
      const elementOf = (answer) => {
        const found = checker.getNonNullableType(answer);
        const listed = found.symbol && found.symbol.name === 'NodeListOf' ? checker.getTypeArguments(found) : [];
        return listed.length ? listed[0] : found;
      };
      return {
        /** @param {any} node */
        CallExpression(node) {
          const callee = node.callee;
          if (
            node.typeArguments ||
            callee.type !== 'MemberExpression' ||
            callee.computed ||
            !QUERY_NAMES.has(callee.property.name)
          )
            return;
          const signature = checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(node));
          const declaration = signature && signature.getDeclaration();
          const parameter = declaration && declaration.typeParameters && declaration.typeParameters[0];
          if (!signature || !parameter || !parameter.default) return; // not the selector-string overload
          const found = checker.typeToString(elementOf(signature.getReturnType()));
          if (found !== 'Element')
            context.report({ node, messageId: 'inferred', data: { name: callee.property.name, found } });
        },
      };
    },
  },
  // A write through a binding another module exports (`OTHER.x = v`, `OTHER.n++`, `delete OTHER.k`): the state
  // belongs to the module that declares it and changes through the functions it exports (ADR-0042 D1). A write to
  // the imported binding itself is no-import-assign's (and a TypeError at run time).
  'no-imported-state-write': {
    meta: {
      type: 'problem',
      messages: { write: "{{name}} is another module's state: change it through a function {{from}} exports." },
      schema: [],
    },
    create(context) {
      /** @type {Map<string, string>} */
      const imported = new Map();
      // The binding a member chain starts from, through the type-only wrappers TypeScript puts round a value (`(OFF as
      // T).n`, `OFF!.n`): they change no value, so a write through them is a write to OFF.
      /** @param {any} node */
      const root = (node) => {
        let n = node;
        while (n.type === 'MemberExpression' || UNWRAP.has(n.type))
          n = n.type === 'MemberExpression' ? n.object : n.expression;
        return n.type === 'Identifier' ? n : null;
      };
      /** @param {import('estree').Node} target @param {import('estree').Node} at */
      const check = (target, at) => {
        if (target.type !== 'MemberExpression') return;
        const id = root(target);
        if (!id || !imported.has(id.name)) return;
        const variable = findVariable(context.sourceCode.getScope(at), id.name);
        if (!variable || !variable.defs.some((d) => d.type === 'ImportBinding')) return; // a local of the same name
        context.report({ node: at, messageId: 'write', data: { name: id.name, from: imported.get(id.name) } });
      };
      return {
        ImportDeclaration(node) {
          for (const s of node.specifiers) imported.set(s.local.name, String(node.source.value));
        },
        AssignmentExpression(node) {
          check(node.left, node);
        },
        UpdateExpression(node) {
          check(node.argument, node);
        },
        UnaryExpression(node) {
          if (node.operator === 'delete') check(node.argument, node);
        },
      };
    },
  },
};

/**
 * The variable named name as seen from scope, looking outwards.
 * @param {import('eslint').Scope.Scope | null} scope
 * @param {string} name
 */
function findVariable(scope, name) {
  for (let s = scope; s; s = s.upper) {
    const v = s.set.get(name);
    if (v) return v;
  }
  return null;
}

// Browser globals whose names read like a local variable, so a missing declaration would silently use the window's
// (`event`, `name`, `status`, ...): code says window.x when it means the window's.
const CONFUSING_GLOBALS = [
  'addEventListener',
  'blur',
  'close',
  'closed',
  'confirm',
  'defaultStatus',
  'event',
  'external',
  'find',
  'focus',
  'frameElement',
  'frames',
  'history',
  'innerHeight',
  'innerWidth',
  'length',
  'location',
  'locationbar',
  'menubar',
  'moveBy',
  'moveTo',
  'name',
  'onblur',
  'onerror',
  'onfocus',
  'onload',
  'onresize',
  'onunload',
  'open',
  'opener',
  'opera',
  'outerHeight',
  'outerWidth',
  'pageXOffset',
  'pageYOffset',
  'parent',
  'print',
  'removeEventListener',
  'resizeBy',
  'resizeTo',
  'screen',
  'screenLeft',
  'screenTop',
  'screenX',
  'screenY',
  'scroll',
  'scrollbars',
  'scrollBy',
  'scrollTo',
  'scrollX',
  'scrollY',
  'self',
  'status',
  'statusbar',
  'stop',
  'toolbar',
  'top',
];

// A type argument on a DOM query (`querySelector<HTMLInputElement>(...)`, `closest<HTMLElement>(...)`) says what class
// the element is without checking it - an assertion no other rule sees. The page's elements by id are declared from
// index.html (types/page.d.ts, docs/adr/0045-viewer-page-elements.md); any other query gives Element | null, narrowed
// with findElement, findMaybe or findAll (js/platform/dom.ts), which check the class.
export const UNCHECKED_QUERIES = [
  {
    selector: 'CallExpression[typeArguments][callee.property.name=/^(querySelector|querySelectorAll|closest)$/]',
    message:
      'A type argument on querySelector, querySelectorAll or closest asserts the element class unchecked: use findElement, findMaybe or findAll (js/platform/dom.ts), which check it.',
  },
];

export default [
  {
    files: ['src/limn/viewer/js/**/*.ts'],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: 'module',
      parser: tseslint.parser,
      parserOptions: { project: './tsconfig.json', tsconfigRootDir: import.meta.dirname },
      globals: {
        ...globals.browser,
        // Filled by the server in the built script (limn/viewer/assemble.py viewer_script); declared for tsc in
        // src/limn/viewer/types/globals.d.ts.
        __LUCIDE_JSON__: 'readonly',
        __UI_EN_JSON__: 'readonly',
      },
    },
    linterOptions: { reportUnusedDisableDirectives: 'error', noInlineConfig: true },
    plugins: { '@typescript-eslint': tseslint.plugin, limn: { rules: limnRules } },
    rules: {
      // No implicit globals: a name tsc cannot find (TS2304) fails npm run typecheck, which also sees the ambient types
      // of src/limn/viewer/types/ that no-undef cannot - so no-undef is not run. A declared browser global that reads like
      // a local variable is still refused here: code says window.x when it means the window's.
      'no-restricted-globals': ['error', ...CONFUSING_GLOBALS],
      // A DOM query says the class of what it found by checking it, not by a type argument.
      'no-restricted-syntax': ['error', ...UNCHECKED_QUERIES],
      'limn/no-inferred-query-class': 'error',
      // State is owned by the module that declares it.
      'no-import-assign': 'error',
      'limn/no-imported-state-write': 'error',
      // No any: values of type any (however they got it), and any written in a type.
      '@typescript-eslint/no-unsafe-assignment': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'error',
      '@typescript-eslint/no-unsafe-call': 'error',
      '@typescript-eslint/no-unsafe-argument': 'error',
      '@typescript-eslint/no-unsafe-return': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      // No type assertion as an escape hatch: `x as T` and `<T>x` say a value has a type without checking it, `x!` that it
      // is not null or undefined. Narrow with a guard (instanceof HTMLElement, a test). `as const` is not reported: it
      // checks the literal and narrows it to itself.
      '@typescript-eslint/consistent-type-assertions': ['error', { assertionStyle: 'never' }],
      '@typescript-eslint/no-non-null-assertion': 'error',
      // No comment that switches the type checker off (@ts-ignore, @ts-expect-error, @ts-nocheck).
      '@typescript-eslint/ban-ts-comment': [
        'error',
        { 'ts-expect-error': true, 'ts-ignore': true, 'ts-nocheck': true, 'ts-check': false },
      ],
      // A type is written in the code, not in a JSDoc comment TypeScript ignores.
      'limn/no-jsdoc-type': 'error',
      // Names are whole words, and a comment carries no history; both are held by the ratchet like the rest.
      'limn/plain-names': 'error',
      'limn/no-history-comment': 'error',
      // A switch over a closed union handles every member, and a default does not stand in for a missing one.
      '@typescript-eslint/switch-exhaustiveness-check': [
        'error',
        {
          allowDefaultCaseForExhaustiveSwitch: false,
          considerDefaultExhaustiveForUnions: false,
          requireDefaultForNonUnion: false,
        },
      ],
    },
  },
];
