/** Manage the document parse worker, validate its replies and expire superseded jobs. */
import { isRecord } from '../platform/tables.ts';
import { MARKDOWN_LIMIT } from '../app/rules-tables.ts';
import { MARKDOWN_LIMITS } from './state.ts';

let MARKDOWN_WORKER: Worker | null = null;
let MARKDOWN_JOB: MarkdownParseJob | null = null;
let MARKDOWN_SEQUENCE = 0;
// ---------------- The parse worker
// A markdown-it token as the parse worker sends it (md-parse.mjs plain: a Token's own fields, as plain data - its
// prototype does not survive postMessage), its inline children alike. An attribute's value is a string, but an ordered
// list's start, which markdown-it keeps as the number its first marker has.
interface MarkdownToken {
  type: string;
  tag: string;
  nesting: number;
  map: [number, number] | null;
  content: string;
  info: string;
  hidden: boolean;
  level: number;
  markup: string;
  attrs: [string, string | number][] | null;
  children: MarkdownToken[] | null;
}
// What the page asks the worker (md-parse.mjs onmessage): the source and the limits it parses within.
interface MarkdownParseQuestion {
  id: number;
  text: string;
  limits: { nesting: number; blocks: number; inlines: number };
}
// The worker's answer to question id (md-parse.mjs postMessage): the tokens; or a limit it hit ('nesting', 'blocks',
// 'inlines') with what it counted and the most allowed; or 'error' with what the parser threw.
type MarkdownParseAnswer =
  | { id: number; ok: true; tokens: MarkdownToken[] }
  | { id: number; ok: false; limit: string; count: number; max: number }
  | { id: number; ok: false; limit: string; message: string };
// What a parse ends with: the worker's answer, or the page's own end of it - the worker did not load or answer in time,
// a NUL it is not given, or an answer of no known form (MARKDOWN_LIMIT).
type MarkdownParse = MarkdownParseAnswer | { ok: false; limit: string };
// A parse in flight: its question's id, what ends it, and the timer that stops it.
interface MarkdownParseJob {
  id: number;
  resolve: (answer: MarkdownParse | null) => void;
  t: ReturnType<typeof setTimeout>;
}
// Whether a value is a token as the worker sends it (plain), its children too. Pure.
function isMarkdownToken(value: unknown): value is MarkdownToken {
  if (!isRecord(value)) return false;
  const { map, attrs, children } = value;
  return (
    typeof value.type === 'string' &&
    typeof value.tag === 'string' &&
    typeof value.nesting === 'number' &&
    (map === null || (Array.isArray(map) && map.length === 2 && map.every((line) => typeof line === 'number'))) &&
    typeof value.content === 'string' &&
    typeof value.info === 'string' &&
    typeof value.hidden === 'boolean' &&
    typeof value.level === 'number' &&
    typeof value.markup === 'string' &&
    (attrs === null ||
      (Array.isArray(attrs) &&
        attrs.every(
          (attribute) =>
            Array.isArray(attribute) &&
            attribute.length === 2 &&
            typeof attribute[0] === 'string' &&
            (typeof attribute[1] === 'string' || typeof attribute[1] === 'number'),
        ))) &&
    (children === null || (Array.isArray(children) && children.every(isMarkdownToken)))
  );
}
// The worker's message as its answer (md-parse.mjs postMessage), or null for a message of no known form. Pure.
function markdownParseAnswer(value: unknown): MarkdownParseAnswer | null {
  if (!isRecord(value) || typeof value.id !== 'number') return null;
  const { id, limit, tokens, count, max, message } = value;
  if (value.ok === true)
    return Array.isArray(tokens) && tokens.every(isMarkdownToken) ? { id, ok: true, tokens } : null;
  if (value.ok !== false || typeof limit !== 'string') return null;
  if (typeof count === 'number' && typeof max === 'number') return { id, ok: false, limit, count, max };
  return typeof message === 'string' ? { id, ok: false, limit, message } : null;
}
// The worker's message to the job in flight: its answer, a parse error for a message to it of no known form, or null
// for a message to another question (one the job took over from) or with no question's id.
function jobAnswer(job: MarkdownParseJob, value: unknown): MarkdownParse | null {
  if (!isRecord(value) || value.id !== job.id) return null;
  return markdownParseAnswer(value) || { ok: false, limit: MARKDOWN_LIMIT.ERROR };
}
// Parses text in the worker within MARKDOWN_LIMITS -> {ok:true,tokens} or {ok:false,limit} (MARKDOWN_LIMIT), or null
// when a newer parse took the worker over. The worker is started the first time and kept; one that runs past
// MARKDOWN_LIMITS.ms, fails to load or is taken over is stopped (terminate) and a new one starts next time.
function parseMarkdown(text: string): Promise<MarkdownParse | null> {
  stopMarkdownParse(null);
  return new Promise((resolve) => {
    let worker = MARKDOWN_WORKER;
    try {
      if (!worker) {
        worker = new Worker('/md-parse.mjs', { type: 'module' });
        MARKDOWN_WORKER = worker;
        worker.onmessage = (message: MessageEvent<unknown>) => {
          const job = MARKDOWN_JOB,
            answer = job && jobAnswer(job, message.data);
          if (!job || !answer) return;
          clearTimeout(job.t);
          MARKDOWN_JOB = null;
          job.resolve(answer);
        };
        worker.onerror = (event) => {
          event.preventDefault();
          stopMarkdownParse({ ok: false, limit: MARKDOWN_LIMIT.LOAD });
        };
      }
    } catch (error) {
      resolve({ ok: false, limit: MARKDOWN_LIMIT.LOAD });
      return;
    }
    const id = advanceMarkdownSequence();
    MARKDOWN_JOB = {
      id,
      resolve,
      t: setTimeout(() => stopMarkdownParse({ ok: false, limit: MARKDOWN_LIMIT.TIME }), MARKDOWN_LIMITS.ms),
    };
    const question: MarkdownParseQuestion = {
      id,
      text,
      limits: { nesting: MARKDOWN_LIMITS.nesting, blocks: MARKDOWN_LIMITS.blocks, inlines: MARKDOWN_LIMITS.inlines },
    };
    worker.postMessage(question);
  });
}
// Ends the parse in flight, if any, with answer (null: taken over), and stops its worker.
function stopMarkdownParse(answer: { ok: false; limit: string } | null) {
  const job = MARKDOWN_JOB;
  if (!job) return;
  MARKDOWN_JOB = null;
  clearTimeout(job.t);
  if (MARKDOWN_WORKER) {
    MARKDOWN_WORKER.terminate();
    MARKDOWN_WORKER = null;
  }
  job.resolve(answer);
}

/** Allocate a question ID shared by the document and comparison workers. */
function advanceMarkdownSequence() {
  return ++MARKDOWN_SEQUENCE;
}

export { parseMarkdown, jobAnswer, advanceMarkdownSequence };
export type { MarkdownParseJob, MarkdownToken, MarkdownParse, MarkdownParseQuestion };
