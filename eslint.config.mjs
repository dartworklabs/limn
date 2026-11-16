// ESLint for the viewer's TypeScript modules (docs/adr/0042-viewer-es-modules.md D7, docs/adr/0043-viewer-typescript.md,
// docs/handbook/viewer.md §타입 검사).
//
// Every rule here is a gate: tools/strict_ratchet.py runs ESLint and holds each file's count per rule to
// tools/strict-baseline.json, which only goes down - a file with more than its baseline fails, and so does one with
// fewer until the baseline is lowered. A file or rule the baseline does not name must have none. `npm run lint` shows
// the messages themselves.
//
// The rules are type-aware: typescript-eslint reads tsconfig.strict.json, the types tsc infers with noImplicitAny (an
// unannotated `let x;` or `[]` takes the type its assignments give it), so a value of type any is found whether it
// came from an annotation, an untyped library or a JSON.parse. The escape hatches are typescript-eslint's rules: an
// explicit any, a type assertion (`x as T`, `<T>x`), a non-null assertion (`x!`) and a @ts- directive. Two checks no
// plugin makes are local rules (limnRules below): a write through another module's binding, and a JSDoc type, which
// TypeScript does not read in a .ts file at all.
import globals from 'globals';
import tseslint from 'typescript-eslint';

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

export default [
  {
    files: ['src/limn/viewer/js/**/*.ts'],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: 'module',
      parser: tseslint.parser,
      parserOptions: { project: './tsconfig.strict.json', tsconfigRootDir: import.meta.dirname },
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
