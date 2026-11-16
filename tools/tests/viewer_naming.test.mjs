// The viewer's naming-and-prose rules on cases of their own (docs/handbook/viewer.md §이름과 주석): limn/plain-names
// (a declared name is whole words, tools/viewer-names.json) and limn/no-history-comment (a comment carries no release
// number, issue number or date stamp). The CI lint job runs them (npm test) before the ratchet, so a rule that stopped
// catching its violation, or began reporting a legal case, fails there.
//
// Run: npm ci --ignore-scripts && npm test
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Linter } from 'eslint';
import tseslint from 'typescript-eslint';
import config, { limnRules } from '../../eslint.config.mjs';
import { historyIn, loadNameLists, nameProblems, quotedSpans, wordsOf } from '../viewer_naming.mjs';

/** The messages one local rule gives code, a TypeScript module: [line, text] pairs. */
function lint(rule, code, filename = 'module.ts') {
  const linter = new Linter({ configType: 'flat' });
  return linter
    .verify(
      code,
      [
        {
          files: ['**/*.ts'],
          languageOptions: { ecmaVersion: 2024, sourceType: 'module', parser: tseslint.parser },
          plugins: { limn: { rules: limnRules } },
          rules: { [`limn/${rule}`]: 'error' },
        },
      ],
      filename,
    )
    .map((m) => [m.line, m.ruleId ? m.message : `fatal: ${m.message}`]);
}

/** The names limn/plain-names reports in code, in order of their position. */
const reportedNames = (code, filename) => lint('plain-names', code, filename).map(([, text]) => text.split(' ')[0]);

/** The lines limn/no-history-comment reports in code. */
const historyLines = (code) => lint('no-history-comment', code).map(([line]) => line);

test('the word lists are well formed, and the two rules are gates in the ESLint config', () => {
  const lists = loadNameLists();
  for (const word of [...lists.english, ...Object.keys(lists.allow), ...lists.loopIndex, ...Object.keys(lists.deny)])
    assert.equal(word, word.toLowerCase(), `${word}: lowercase`);
  assert.ok(
    lists.english.every((word) => word.length < 3),
    'english lists short words only',
  );
  for (const [word, reason] of Object.entries(lists.allow)) {
    assert.ok(typeof reason === 'string' && reason.trim(), `allow ${word} needs a reason`);
    assert.ok(word.length < 3 || word === 'i18n', `allow ${word}: a word of three letters needs no entry`);
    assert.ok(!(word in lists.deny), `${word} is both allowed and denied`);
  }
  for (const [word, whole] of Object.entries(lists.deny)) {
    assert.ok(word.length >= 3, `deny ${word}: a short word is refused already`);
    assert.ok(typeof whole === 'string' && whole.trim(), `deny ${word} needs the whole word`);
  }
  assert.ok(lists.loopIndex.every((name) => name.length === 1));
  const rules = config.find((entry) => entry.rules && entry.rules['limn/plain-names']).rules;
  assert.equal(rules['limn/plain-names'], 'error');
  assert.equal(rules['limn/no-history-comment'], 'error');
});

test('a name is split into words at case changes, underscores and digits', () => {
  assert.deepEqual(wordsOf('pvPress'), ['pv', 'press']);
  assert.deepEqual(wordsOf('PV_BUSY'), ['pv', 'busy']);
  assert.deepEqual(wordsOf('MdRx'), ['md', 'rx']);
  assert.deepEqual(wordsOf('parseHTMLDoc'), ['parse', 'html', 'doc']);
  assert.deepEqual(wordsOf('getXY'), ['get', 'xy']);
  assert.deepEqual(wordsOf('h264'), ['h', '264']);
  assert.deepEqual(wordsOf('I18N_EN'), ['i18n', 'en']);
  assert.deepEqual(wordsOf('_unused'), ['unused']);
  assert.deepEqual(wordsOf('$$'), []);
  assert.deepEqual(wordsOf('_'), []);
});

test('an abbreviated or too-short word in a declared name is refused, and the message names the word and why', () => {
  const lists = loadNameLists();
  for (const name of [
    'pvPress',
    'vdRefocus',
    'PV_BUSY',
    'mdcRow',
    'rdStart',
    'txLine',
    'ccSend',
    'c',
    'f',
    'el',
    'T',
    'e2',
  ]) {
    assert.notDeepEqual(nameProblems(name, lists), [], name);
  }
  assert.deepEqual(nameProblems('pvPress', lists), [
    '"pv" is shorter than 3 letters and not in the short-word allow-list: write the whole word',
  ]);
  assert.deepEqual(nameProblems('selStart', lists), ['"sel" abbreviates "selection": write the whole word']);
  assert.deepEqual(nameProblems('msgBtn', lists).length, 2, 'every refused word is told');
  assert.deepEqual(nameProblems('pvPv', lists).length, 1, 'the same word is told once');
});

test('whole words, the allow-lists and acronyms of three letters or more pass', () => {
  const lists = loadNameLists();
  for (const name of [
    'pinState',
    'layoutFor',
    'isMac',
    'toId',
    'x',
    'y',
    'x0',
    'scrollTo',
    'IS_MAC',
    'URL',
    'PDF',
    'HTML',
    'CSS',
    'DOM',
    'IME',
    'imeKey',
    'err',
    'off',
    'offline',
    'selection',
    'reverse',
    'resolve',
    'second',
    'I18N_EN',
    'UI_LANG',
    'NOTICE_MS',
    'BAND_HOLD_PX',
    'OFF_DB',
    'byId',
    'okAt',
    'parseHTMLDoc',
    'utf8',
    '$',
    '$$',
    '_',
    '_unused',
    'fyi',
    'doc',
  ]) {
    assert.deepEqual(nameProblems(name, lists), [], name);
  }
});

test('i, j and k pass only as the whole name of a loop index', () => {
  const lists = loadNameLists();
  assert.deepEqual(nameProblems('i', lists, true), []);
  assert.deepEqual(nameProblems('k', lists, true), []);
  assert.notDeepEqual(nameProblems('i', lists, false), []);
  assert.notDeepEqual(nameProblems('iTotal', lists, true), []);
  assert.notDeepEqual(nameProblems('ii', lists, true), []);
  assert.deepEqual(reportedNames('for (let i = 0; i < 3; i++) {\n  for (let j = 0; j < i; j++) void j;\n}\n'), []);
  assert.deepEqual(
    reportedNames('const rows: string[] = [];\nfor (const k in rows) void k;\nfor (const i of rows) void i;\n'),
    [],
  );
  assert.deepEqual(reportedNames('const rows: number[] = [];\nrows.forEach((row, i) => void (row + i));\n'), ['i']);
  assert.deepEqual(reportedNames('let i = 0;\nvoid i;\n'), ['i']);
  assert.deepEqual(reportedNames('for (let n = 0; n < 3; n++) void n;\n'), ['n']);
});

test('every kind of declaration is reported at its declaration, once, and its uses are not', () => {
  const code = [
    'import * as pv from "./a.ts";',
    'import md from "./b.ts";',
    'import { thing as th } from "./c.ts";',
    'function pvPress(c: number, ...rs: number[]) { return c + rs.length; }',
    'const vdRefocus = (f: number) => f;',
    'let PV_BUSY = 0;',
    'class Rd { declare rv: number; }',
    'type Tx = number;',
    'interface Cc { n: number }',
    'function pick<T>(items: T[]): T { return items[0]; }',
    'try { pv.run(); } catch (e) { void e; }',
    'const { ime, off: ff } = md;',
    'void [pvPress, vdRefocus, PV_BUSY, Rd, ime, ff, th];',
    'let tx: Tx = 1; tx = 2; void tx; void ({} as Cc);',
  ].join('\n');
  assert.deepEqual(reportedNames(code), [
    ...['pv', 'md', 'th', 'pvPress', 'c', 'rs', 'vdRefocus', 'f', 'PV_BUSY', 'Rd', 'Tx', 'Cc', 'T', 'e', 'ff', 'tx'],
  ]);
});

test('a use, a property name, an object key and an unchanged import name are not declarations', () => {
  assert.deepEqual(
    reportedNames('const settings = { pv: 1, md: 2 };\nvoid settings.pv;\nvoid settings.md;\nvoid settings["c"];\n'),
    [],
  );
  assert.deepEqual(
    reportedNames('class Panel { declare pv: number; md() { return this.pv; } }\nvoid new Panel().md();\n'),
    [],
  );
  assert.deepEqual(
    reportedNames(
      'import { pvPress } from "./verdict.ts";\nimport { vdRefocus as refocusVerdict } from "./verdict.ts";\nvoid [pvPress, refocusVerdict];\n',
    ),
    [],
  );
  assert.deepEqual(reportedNames('import { vdRefocus as vr } from "./verdict.ts";\nvoid vr;\nvoid vr;\n'), ['vr']);
  assert.deepEqual(reportedNames('const pinCount = 1;\nconst c = pinCount;\nvoid c;\nvoid c;\nvoid c;\n'), ['c']);
});

test('one report for a declaration however many names a type and a value share, and none in a .d.ts', () => {
  assert.deepEqual(reportedNames('const Tx = 1;\ntype Tx = number;\nvoid Tx;\n'), ['Tx']);
  assert.deepEqual(
    reportedNames('declare function pvPress(c: number): void;\nexport type Cc = { n: number };\n', 'types.d.ts'),
    [],
  );
});

test('a destructured or parameter name is reported where it is bound', () => {
  assert.deepEqual(reportedNames('const { first: f, second } = { first: 1, second: 2 };\nvoid [f, second];\n'), ['f']);
  assert.deepEqual(
    reportedNames('function line({ lo, hi }: { lo: number; hi: number }) { return hi - lo; }\nvoid line;\n'),
    ['lo', 'hi'],
  );
});

test('a comment with a release number, an issue number or a date is refused, once per comment', () => {
  for (const comment of [
    '// Changed in 0.4.34: the key moves the focus.',
    '/* Since 0.4.5 the tip says so. */',
    '// The note popover (issue #185).',
    '// Fixes #418.',
    '// reported in PR #11 review',
    '// Pull request #7 added it.',
    '// QA 2026-09-24: the bar clipped.',
    '/** Saved before 0.4.41 as 0. */',
  ]) {
    assert.deepEqual(historyLines(`${comment}\nconst note = 1;\nvoid note;\n`), [1], comment);
  }
  assert.deepEqual(
    historyLines('/* 0.4.1 and 0.4.2 and #123 and #456 and 2026-01-02 */\nvoid 0;\n'),
    [1],
    'one report per comment',
  );
  assert.deepEqual(historyLines('// a #12\n// b\n// c #34\n'), [1, 3], 'each // line is its own comment');
});

test('a reference to a rule that holds now, an address, a quoted example and a specification number pass', () => {
  for (const comment of [
    '// A pin of a Markdown document has no page (ADR-0025 D2): its head says the lines alone.',
    '// docs/handbook/viewer.md §패널 정리 and architecture.md §멈춤 신호',
    '// The keys only move the focus (WCAG 3.2.2): Enter chooses.',
    '// Loopback is 127.0.0.1, 0.0.0.0/8 and 127.0.0.0/8; the trailing dot of "127.0.0.1." is dropped.',
    '// Spec: https://example.com/v1.2.3/page#12 and http://localhost:8080/#99',
    '// Pinned to https://cdn.example.com/lib/1.2.3/lib.js, which the page loads.',
    '/** @version 1.2.3 */',
    "// The head says '#12 deleted pin' for a pin in the Trash, '#12;' stays text.",
    '// The tab title: "Limn · #14 · 3쪽", and a time as `2025-09-25 00:01`.',
    '// The bar (#bar1) and a hash like #doc=<key> or &#169; or #fff or #1a73e8 are not issue numbers.',
    '// A number is `#N`, and a one-digit step #1 is not an issue.',
    "// The pin's own '#42 saved' line stays on the status line.",
    "// Written as html`` values, a '#12' whose pin exists is a link.",
  ]) {
    assert.deepEqual(historyLines(`${comment}\nconst note = 1;\nvoid note;\n`), [], comment);
  }
});

test('a quote that spans the lines of a // run holds its example, and an apostrophe opens no quote', () => {
  assert.deepEqual(
    historyLines("// The line says ('이유는 이전 판정 #15 채택에\n// 저장됨 · 지금 판정은 #16 보류').\nvoid 0;\n"),
    [],
  );
  assert.deepEqual(historyLines("// The page's verdict's number is #15 now.\nvoid 0;\n"), [1]);
  assert.deepEqual(
    historyLines("// A verdict about page `page`'s whole target, saved: '#42 saved' on the line.\nvoid 0;\n"),
    [],
  );
  assert.deepEqual(historyLines("// A commit's subject, a squash merge's text, then #15 (issue).\nvoid 0;\n"), [1]);
  assert.deepEqual(historyLines("// What is said 'in quotes\n// on two lines', and #15 outside.\nvoid 0;\n"), [2]);
});

test('historyIn says each kind it found, and quotedSpans reads quotes', () => {
  assert.deepEqual(historyIn('Changed in 0.4.34 (issue #418, 2026-09-24).'), [
    { kind: 'release', text: '0.4.34' },
    { kind: 'issue', text: 'issue #418' },
    { kind: 'date', text: '2026-09-24' },
  ]);
  assert.deepEqual(historyIn('a 0.4.34 b #12 c', 0, 5), [{ kind: 'release', text: '0.4.34' }]);
  assert.deepEqual(quotedSpans("a pin's '#12' and `x`"), [
    [8, 13],
    [18, 21],
  ]);
  assert.deepEqual(quotedSpans("pin's"), []);
});
