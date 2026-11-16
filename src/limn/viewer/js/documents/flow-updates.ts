// ------------------------------------------------ What came while you were viewing (docs/handbook/viewer.md §새 소식)
// Said from reads the viewer already makes - no new field, no event type, nothing written on a GET (ADR-0027):
// - a document changed (a merge the instance pulled, a push, a file edited where the instance serves it, a figure or
//   PDF that came again): one message per document, '본문이 바뀌었습니다 — PR #12 서론 다듬기 · Bob Park · 핀 2개 줄
//   이동', with [변경 보기] (the changes view on exactly the new commits) or, on a Markdown or text document, [바뀐 곳]
//   (the changed lines, tinted while the message stands). It stands until [x] or its action - only then is the change
//   seen - and each later change of that document merges into it. What a person has seen is kept per device
//   (localStorage limnSeen), so a reload, another document or a visit days later still says what changed since;
// - others' new pins (a co-author's, an agent's), one message per document, [보기];
// - this page is older than the Limn the server runs now (GET /api/version): a status item with [새로 고침]
//   (documents/view-status.ts);
// - back after a while, what came meanwhile is said as one message (platform/notices.ts digestBegin,
//   documents/flow-polling.ts).
import {
  DOC,
  DOCS,
  META,
  META_BY,
  REPLY,
  REPLY_DRAFT,
  SWITCHSEQ,
  isFigureKind,
  isViewOnlyKind,
  rendersInBrowser,
} from '../app/state.ts';
import { translateTemplate, translate, josaName } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { GROUPS, flushDeferred, groupNote, groupRedraw, lineNote } from '../platform/notices.ts';
import { REVISION_VIEW, loadRevisions, setViewMode } from '../revisions/flow.ts';
import { switchDoc } from './flow-switch.ts';
import { notifyCursor, openPinFromLink } from '../pins/flow-notification.ts';
import { drawStatus } from './view-status.ts';
import { MARKDOWN_VIEW, lineLeaves, showLines } from '../markdown/view.ts';
import { replyNote } from '../pins/flow-reply.ts';
import { editDirty } from '../pins/flow-edit.ts';
import { NOTICE_DOT, NOTICE_KIND } from '../platform/tables.ts';
import { $$ } from '../platform/dom.ts';
import { VIEW_MODE } from '../app/rules-tables.ts';
import { who } from '../app/state-people.ts';
import { isMarkdownDoc, docInfo, withDocQuery, pdoc, REVISION_PAGE } from './state.ts';
const UPDATE_STATE = {
  moved: new Map() as Map<string, { moved: Set<number>; lost: Set<number> }>,
  lines: new Map() as Map<string, { base: string[]; ranges: { lo: number; hi: number }[]; at: number }>,
  expect: 0,
  expectAt: 0,
  seenAt: new Map() as Map<string, number>,
  top: null as number | null,
  checking: new Map() as Map<string, { ver: string; again: boolean }>,
}; // document -> the check reading its history: its version, and whether a call left it to that check
// after a source change is seen, how long its pins' moves wait for the document's update message
const UPDATE_EXPECT_MS = 120000;
const DIGEST_TAIL_MS = 2500; // how long a gathering waits after its poll for the build and the update it set going
const LINE_DIFF_MAX = 500; // edit steps the line comparison tries before calling the whole middle one changed place

// ---------------- What a person has seen (localStorage limnSeen: {v, pin, docs:{<key>:{ver, rev}}})
// ver names what a document showed (its build on screen, or a drawn document's source mtime), rev its newest commit
// then ('' without history); pin the highest pin number whose arrival was said. Another browser or device keeps its
// own. A browser whose storage refuses (a SecurityError, a full quota) keeps it in memory for this visit (SEEN_MEM)
// from the first refusal.
let SEEN_MEM = null as string | null;
function seenStore(): { v?: number; pin?: number; docs?: Record<string, { ver: string; rev: string }> } {
  let raw = SEEN_MEM;
  if (raw === null)
    try {
      raw = localStorage.getItem('limnSeen');
    } catch (error) {
      raw = SEEN_MEM = '{}';
    }
  try {
    const parsed = JSON.parse(raw || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (error) {
    return {};
  }
}
function seenSave(all: { v?: number; pin?: number; docs?: Record<string, { ver: string; rev: string }> }) {
  all.v = 1;
  const raw = JSON.stringify(all);
  if (SEEN_MEM !== null) {
    SEEN_MEM = raw;
    return;
  }
  try {
    localStorage.setItem('limnSeen', raw);
  } catch (error) {
    SEEN_MEM = raw;
  }
}
function seenDoc(doc: string): { ver: string; rev: string } | null {
  const record = (seenStore().docs || {})[doc];
  return record && typeof record.ver === 'string' ? { ver: record.ver, rev: String(record.rev || '') } : null;
}
// Records `record` as what `doc` showed when seen - unless the record kept already names a later version (verAfter):
// another tab of this browser saw a newer one meanwhile, and an old tab dismissing its older message never takes that
// back.
function setSeenDoc(doc: string, record: { ver: string; rev: string }) {
  const all = seenStore(),
    was = (all.docs || {})[doc];
  if (was && typeof was.ver === 'string' && verAfter(was.ver, record.ver)) return;
  all.docs = { ...(all.docs || {}), [doc]: record };
  seenSave(all);
}
// Whether `version` (limnSeen's ver) is later than `other`: a drawn document's source mtime ('src:<seconds>') by its
// number, a built one's build id ('build:pages-<YYYYMMDDHHMMSS>[-<n>]', the server's names) by its time and then its
// count. Versions of different kinds are not ordered (false). Pure.
function verAfter(version: string, other: string): boolean {
  const sourcePattern = /^src:(.+)$/,
    buildPattern = /^build:pages(?:-(\d{14})(?:-(\d+))?)?$/,
    versionSource = sourcePattern.exec(version),
    otherSource = sourcePattern.exec(other);
  if (versionSource && otherSource) return Number(versionSource[1]) > Number(otherSource[1]);
  const versionBuild = buildPattern.exec(version),
    otherBuild = buildPattern.exec(other);
  if (!versionBuild || !otherBuild) return false;
  const versionTime = versionBuild[1] || '',
    otherTime = otherBuild[1] || '';
  return versionTime !== otherTime
    ? versionTime > otherTime
    : Number(versionBuild[2] || 0) > Number(otherBuild[2] || 0);
}
// Whether this device was here before: it has a seen record or an event cursor (pins/flow-notification.ts).
function visitedBefore() {
  return !!seenStore().v || notifyCursor() !== null;
}
function seenPin(): number | null {
  const highest = seenStore().pin;
  return typeof highest === 'number' ? highest : null;
}
function setSeenPin(pin: number) {
  const all = seenStore();
  if (typeof all.pin === 'number' && all.pin >= pin) return;
  all.pin = pin;
  seenSave(all);
}

// ---------------- Pure rules
// The PR number a commit subject names: a merge commit's 'Merge pull request #12 …', a squash merge's '… (#12)'; 0 for
// none.
function pullRequestOf(subject: unknown): number {
  const text = String(subject || ''),
    match = /^Merge pull request #(\d+)/.exec(text) || /\(#(\d+)\)\s*$/.exec(text);
  return match ? +match[1] : 0;
}
// The commits above the last seen one (seen: its id or a prefix) in rows (newest first, /api/revisions): how many (all
// of them when seen is not among them: more), their PRs and authors, the newest one's subject without its '(#12)' - a
// merge commit's own subject is passed over for the commit under it - and time, and the newest id (top). Nothing when
// there are no rows (no history). unknown: which of them are new cannot be told - the rows are not known (null: what
// the shown build carries is not known, shownRows) or no commit was known as seen ('') - so none is named, and top is
// the newest of the rows known ('' for none). Pure.
function describeCommits(rows: { id: string; subject: string; author?: string; time?: string }[] | null, seen: string) {
  const top = rows && rows.length ? rows[0].id : '',
    none = {
      n: 0,
      more: false,
      prs: [] as number[],
      authors: [] as string[],
      subject: '',
      time: '',
      top,
      unknown: false,
    };
  if (!rows || (rows.length && !seen)) return { ...none, unknown: true };
  if (!rows.length) return none;
  const at = rows.findIndex((row) => row.id === seen || row.id.startsWith(seen)),
    fresh = at < 0 ? rows : rows.slice(0, at);
  const plain = fresh.find((row) => !/^Merge (pull request|branch)\b/.test(row.subject)) || fresh[0];
  return {
    n: fresh.length,
    more: at < 0,
    prs: [...new Set(fresh.map((row) => pullRequestOf(row.subject)).filter(Boolean))],
    authors: [...new Set(fresh.map((row) => String(row.author || '')).filter(Boolean))],
    subject: plain ? String(plain.subject).replace(/\s*\(#\d+\)\s*$/, '') : '',
    time: fresh.length ? String(fresh[0].time || '') : '',
    top,
    unknown: false,
  };
}
// Where the lines now (after) differ from the lines before: the changed lines of `after` as ranges {lo, hi} (1-based,
// in order); a place where lines only went away is the line after it (the last line at the end). Common heads and tails
// are set aside, the middle is compared line by line (Myers) up to max edit steps, past that the whole middle is one
// place. Pure.
function lineChanges(before: string[], after: string[], max: number): { lo: number; hi: number }[] {
  let head = 0;
  while (head < before.length && head < after.length && before[head] === after[head]) head++;
  let tail = 0;
  while (
    tail < before.length - head &&
    tail < after.length - head &&
    before[before.length - 1 - tail] === after[after.length - 1 - tail]
  )
    tail++;
  const middleBefore = before.slice(head, before.length - tail),
    middleAfter = after.slice(head, after.length - tail),
    beforeCount = middleBefore.length,
    afterCount = middleAfter.length;
  if (!beforeCount && !afterCount) return [];
  const at = (line: number) => Math.max(1, Math.min(after.length, line));
  if (!afterCount) return [{ lo: at(head + 1), hi: at(head + 1) }];
  if (!beforeCount) return [{ lo: head + 1, hi: head + afterCount }];
  const limit = Math.min(beforeCount + afterCount, max),
    offset = limit + 1,
    furthest = new Int32Array(2 * limit + 3),
    trace: Int32Array<ArrayBuffer>[] = [];
  let end = -1;
  for (let distance = 0; distance <= limit && end < 0; distance++) {
    trace.push(furthest.slice());
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      let x =
          diagonal === -distance ||
          (diagonal !== distance && furthest[offset + diagonal - 1] < furthest[offset + diagonal + 1])
            ? furthest[offset + diagonal + 1]
            : furthest[offset + diagonal - 1] + 1,
        y = x - diagonal;
      while (x < beforeCount && y < afterCount && middleBefore[x] === middleAfter[y]) {
        x++;
        y++;
      }
      furthest[offset + diagonal] = x;
      if (x >= beforeCount && y >= afterCount) {
        end = distance;
        break;
      }
    }
  }
  if (end < 0) return [{ lo: head + 1, hi: head + afterCount }];
  const mark = new Uint8Array(afterCount + 1);
  let x = beforeCount,
    y = afterCount;
  for (let distance = end; distance > 0; distance--) {
    const snapshot = trace[distance],
      diagonal = x - y,
      previousDiagonal =
        diagonal === -distance ||
        (diagonal !== distance && snapshot[offset + diagonal - 1] < snapshot[offset + diagonal + 1])
          ? diagonal + 1
          : diagonal - 1,
      previousX = snapshot[offset + previousDiagonal],
      previousY = previousX - previousDiagonal;
    while (x > previousX && y > previousY) {
      x--;
      y--;
    }
    if (x === previousX) mark[previousY] = 1;
    else if (!mark[previousY]) mark[previousY] = 2; // 1: B[py] came in; 2: lines of A went away before B[py]
    x = previousX;
    y = previousY;
  }
  const out: { lo: number; hi: number }[] = [];
  let runStart = -1;
  for (let i = 0; i <= afterCount; i++) {
    const add = i < afterCount && mark[i] === 1,
      del = mark[i] === 2;
    if (add) {
      if (runStart < 0) runStart = i;
      continue;
    }
    if (runStart >= 0) {
      out.push({ lo: head + runStart + 1, hi: head + i });
      runStart = -1;
    }
    if (del) {
      const line = at(head + i + 1);
      const last = out[out.length - 1];
      if (!last || last.hi < line - 1) out.push({ lo: line, hi: line });
    }
  }
  return out;
}
// The pins in rows numbered above top, not made by me (my login): the new ones others made. Pure.
function freshPins(rows: Pin[], top: number, me: string): Pin[] {
  return (rows || [])
    .filter((pin) => pin.id > top && !(pin.author && me && pin.author.login === me))
    .sort((first, second) => first.id - second.id);
}
// How long a person was away, as the gathered message's title says it: minutes, hours, then days. Pure but for
// translateTemplate().
/** @param lost the connection was what was gone */
function awayTitle(ms: number, lost: boolean): string {
  const minutes = Math.max(1, Math.round(ms / 60000)),
    span =
      minutes < 60
        ? translateTemplate('{n}분', { n: minutes })
        : minutes < 1440
          ? translateTemplate('{n}시간', { n: Math.round(minutes / 60) })
          : translateTemplate('{n}일', { n: Math.round(minutes / 1440) });
  return translateTemplate(lost ? '연결이 끊긴 사이 ({t})' : '자리를 비운 사이 ({t})', { t: span });
}

// ---------------- A document changed
// The document `doc` as it shows now - its name, kind and ver (what limnSeen keeps) - from its meta on screen or its
// entry in the document list; null before it is known.
function shownDocState(doc: string): { ver: string; name: string; kind: string } | null {
  const meta = doc === DOC ? META : META_BY.get(doc),
    entry = docInfo(doc),
    kind = (entry && entry.kind) || (meta && meta.kind) || '',
    source = (meta || entry) as any;
  if (!source) return null;
  // a drawn document on screen: its source as last read (MARKDOWN_VIEW.mtime), not the meta it was opened with; off
  // screen: the document list's (noteOtherDocs keeps it fresh) - MARKDOWN_VIEW still holds the lines of one drawn
  // before, as they were when left
  const sourceTime =
    doc === DOC && MARKDOWN_VIEW.doc === doc && typeof MARKDOWN_VIEW.mtime === 'number'
      ? MARKDOWN_VIEW.mtime
      : doc !== DOC && entry && typeof entry.src_mtime === 'number'
        ? entry.src_mtime
        : source.src_mtime;
  const ver = rendersInBrowser(kind)
    ? typeof sourceTime === 'number'
      ? 'src:' + sourceTime
      : ''
    : source.pages_build
      ? 'build:' + source.pages_build
      : '';
  return ver ? { ver, name: (entry && entry.name) || (meta && meta.doc_name) || doc, kind } : null;
}
// A document's commits, newest first ([] without history), or null when they could not be read.
async function docRows(doc: string): Promise<RevisionRow[] | null> {
  try {
    const answer = (
      await api(withDocQuery('/api/revisions?limit=' + REVISION_PAGE, doc), { what: '변경사항 읽기', silent: true })
    ).data;
    return answer.available ? ((answer.revisions || []) as RevisionRow[]) : [];
  } catch (error) {
    return null;
  }
}
// What a document's shown build was made from, for a built one: the commit its pages came from (the meta's head, ''
// outside git or unknown) and whether the checkout has moved past it (stale_build: its sources changed since); a drawn
// document shows the checkout's source ({head:'', behind:false}). From the meta on screen or kept, else the document's
// light meta; null when that shows another build than now's (a newer one came meanwhile) or cannot be read.
async function docBuild(
  doc: string,
  now: { ver: string; kind: string },
): Promise<{ head: string; behind: boolean } | null> {
  if (rendersInBrowser(now.kind)) return { head: '', behind: false };
  let meta = (doc === DOC ? META : META_BY.get(doc)) as any;
  if (!meta || 'build:' + meta.pages_build !== now.ver) {
    try {
      meta = (await api(withDocQuery('/api/meta?light=1', doc), { what: '상태 확인', silent: true })).data;
    } catch (error) {
      return null;
    }
  }
  if (!meta || 'build:' + meta.pages_build !== now.ver) return null;
  const head = String(meta.head || '');
  return { head: /^[0-9a-f]{4,40}$/i.test(head) ? head : '', behind: !!meta.stale_build };
}
// The commits of a document that its shown build carries, of rows (its history from the checkout, newest first): from
// the build's commit (head, a prefix will do) down when that is one of them; when it is not - the build's commit
// touched none of the document's files - all of them, unless the build is behind the checkout (behind): then which of
// them it carries is not known (null) - the reads say neither where the build's commit stands among them nor which of
// them it lacks, and a guess would name a commit it had already as new. A drawn document: all. Pure.
function shownRows(rows: RevisionRow[], head: string, behind: boolean): RevisionRow[] | null {
  const index = head ? rows.findIndex((row) => row.id.startsWith(head)) : -1;
  return index >= 0 ? rows.slice(index) : behind && rows.length ? null : rows;
}
// Whether a document changed since this device last saw it, and if so says so (docUpdateNote). The first visit of a
// document on a device, and this tab's own rebuild that brought nothing new (context.mine), record what shows as seen -
// unless a change not yet seen stands, which the rebuild then joins. What shows is the shown build's (docBuild): its
// commit, not the checkout's newest - a checkout pulled ahead of the pages still has those commits to say when their
// build comes. When which commits it carries is not known (shownRows), no commit is recorded (''): the next change then
// names none (describeCommits). What shows being older than what this device has seen (verAfter) is no change: this tab
// has not caught up yet - a drawn document come back to shows the lines it was left with until it draws its source
// again, whose change was said while it was off screen - and the read that catches up has nothing new to say either.
// What this device has seen is read again once the history has answered: another tab (limnSeen is shared) may have seen
// this version or a later one meanwhile - then nothing is said, and what this tab kept for the change (its tinted
// lines, its counted moves) goes as if its message had been seen (forgetUpdate) - or a version between the one read
// first and this one: the commits are counted from its commit. Whether this is a first visit is decided again then: a
// record another tab made meanwhile of this version or a later one stays - this answer may name an older commit - and
// one of an earlier version makes it a change to say. A history (or a build) that could not be read is not known, never
// an empty one: the check gives up, records nothing and asks again for the calls it stood for.
async function checkDocUpdate(doc: string, context: { mine?: boolean }) {
  if (!doc) return;
  const now = shownDocState(doc);
  if (!now) return;
  const seen = seenDoc(doc),
    open = GROUPS.has('upd:' + doc);
  if (seen && ((seen.ver === now.ver && !open) || verAfter(seen.ver, now.ver))) return;
  const first = !seen || (!!context.mine && !open);
  if (seen && !first && seen.ver === now.ver) return;
  // A check of this version is reading the history: it says it - and if it gives up (its reads failed, or another
  // version came), it asks again for the calls it stood for (again), so no version is left unchecked by one that did
  // not finish.
  const out = UPDATE_STATE.checking.get(doc);
  if (!context.mine && out && out.ver === now.ver) {
    out.again = true;
    return;
  }
  const mark = { ver: now.ver, again: false };
  UPDATE_STATE.checking.set(doc, mark);
  let rows, build;
  try {
    [rows, build] = await Promise.all([docRows(doc), docBuild(doc, now)]);
  } finally {
    if (UPDATE_STATE.checking.get(doc) === mark) UPDATE_STATE.checking.delete(doc);
  }
  const current = shownDocState(doc);
  // gave up - a newer change's own check says it (the redraw asks)
  if (!current || current.ver !== now.ver) {
    if (mark.again) checkDocUpdate(doc, {});
    return;
  }
  // what this device has seen, read again, decides first - before any asking again, which would stop at that record and
  // leave this tab's tint: another tab may have recorded this version or a later one meanwhile - a first visit's late
  // answer never overwrites that (its commit may be older) - or a message of this document come
  const kept = seenDoc(doc),
    last = kept || seen,
    other = !!kept && (!seen || kept.ver !== seen.ver || kept.rev !== seen.rev);
  const fresh = !last || (!!context.mine && !GROUPS.has('upd:' + doc));
  if (last && (!fresh || other) && (last.ver === now.ver || verAfter(last.ver, now.ver))) {
    if (!GROUPS.has('upd:' + doc)) forgetUpdate(doc);
    return;
  }
  // a build that could not be read is not known; a history that could not be read is no empty history: a call left to
  // this check asks again, else which commits are new is not known - the version is still seen or said, its commits
  // unnamed (as for a build behind its checkout)
  if (!build) {
    if (mark.again) checkDocUpdate(doc, {});
    return;
  }
  if (!rows && mark.again) {
    checkDocUpdate(doc, {});
    return;
  }
  const shown = rows ? shownRows(rows, build.head, build.behind) : null;
  if (fresh || !last) {
    setSeenDoc(doc, { ver: now.ver, rev: !shown ? '' : shown.length ? shown[0].id : last ? last.rev : '' });
    return;
  }
  const commits = describeCommits(shown, last.rev);
  groupNote(
    'upd:' + doc,
    {
      key: doc,
      name: now.name,
      kind: now.kind,
      ver: now.ver,
      seenRev: last.rev,
      top: commits.unknown ? commits.top : commits.top || last.rev,
      commits,
      history: !rows || rows.length > 0,
    },
    docUpdateView,
    null,
  );
}
// Every document, the one on screen first: what changed since this device last saw it (boot).
function checkDocsSeen() {
  [DOC, ...DOCS.map((entry) => entry.key).filter((doc) => doc !== DOC)].forEach((doc) => {
    if (doc) checkDocUpdate(doc, {});
  });
}
// What a document's update message says (groupNote's view): '<name>이(가) 바뀌었습니다' and then the commits (one: its
// PR and subject and author; several: how many, their PRs and authors; none named when which are new is not known), the
// places a drawn document changed, the pins it moved or lost. Its action: [바뀐 곳] on a drawn document of this visit
// with places, else [변경 보기] when there are commits (the changes view on just them, or as it opens when which are
// new is not known), [열기] for another document - whose message stands behind this one's (back) - none otherwise. It
// is seen - limnSeen takes it - once it goes by [x] or its action; a message pushed off the line is not seen and comes
// again on the next visit.
function docUpdateView(update: any) {
  const doc = update.key,
    commits = update.commits,
    here = doc === DOC,
    parts: string[] = [],
    moves = UPDATE_STATE.moved.get(doc),
    lines = here ? UPDATE_STATE.lines.get(doc) : null;
  if (commits.unknown) {
    /* the change is said without its commits */
  } else if (commits.n === 1) {
    parts.push((commits.prs[0] ? 'PR #' + commits.prs[0] + ' ' : '') + commits.subject);
    if (commits.authors[0]) parts.push(commits.authors[0]);
  } else if (commits.n > 1) {
    parts.push(translateTemplate(commits.more ? '커밋 {n}개 넘게' : '커밋 {n}개', { n: commits.n }));
    if (commits.prs.length)
      parts.push(
        commits.prs
          .slice(0, 3)
          .map((pullRequest: number) => 'PR #' + pullRequest)
          .join(', ') + (commits.prs.length > 3 ? ' …' : ''),
      );
    if (commits.authors.length)
      parts.push(
        commits.authors.slice(0, 2).join(', ') +
          (commits.authors.length > 2 ? ' ' + translateTemplate('외 {n}명', { n: commits.authors.length - 2 }) : ''),
      );
  } else
    parts.push(
      translate(
        isFigureKind(update.kind)
          ? '그림을 새로 가져왔습니다'
          : isViewOnlyKind(update.kind)
            ? 'PDF를 새로 그렸습니다'
            : '커밋 없이 파일이 바뀌었습니다',
      ),
    );
  if (lines && lines.ranges.length) parts.push(translateTemplate('바뀐 곳 {n}', { n: lines.ranges.length }));
  if (moves && moves.moved.size) parts.push(translateTemplate('핀 {n}개 줄 이동', { n: moves.moved.size }));
  if (moves && moves.lost.size) parts.push(translateTemplate('핀 {n}개 위치 잃음', { n: moves.lost.size }));
  const act = !here
    ? { label: '열기', tip: '그 문서로 바꿉니다', fn: () => switchDoc(doc) }
    : lines && lines.ranges.length
      ? {
          label: '바뀐 곳',
          tip: '바뀐 줄로 갑니다. 다시 누르면 다음 곳으로 갑니다',
          stay: true,
          fn: () => goToNextChange(doc),
        }
      : commits.unknown && update.history
        ? { label: '변경 보기', tip: '변경 보기를 엽니다', fn: () => openUpdateRange(doc, '') }
        : commits.n > 0 && update.history
          ? {
              label: '변경 보기',
              tip: '새로 들어온 커밋만 변경 보기에서 엽니다',
              fn: () => openUpdateRange(doc, update.seenRev, update.top),
            }
          : null;
  const title = translateTemplate('{name}{p} 바뀌었습니다', {
    name: update.name,
    p: josaName(update.name, '이', '가'),
  });
  return {
    msg: parts.length ? title + ' — ' + parts.join(' · ') : title,
    kind: NOTICE_KIND.INFO,
    act,
    o: {
      literal: true,
      keep: true,
      back: !here,
      brief: title,
      onEnd: (acted: boolean, seen: boolean) => {
        if (acted || seen) docUpdateSeen(doc, update);
      },
    },
  };
}
// A document's update message has been seen: limnSeen takes what it said, and its moved pins and changed lines go
// (forgetUpdate). A record of the message's own version is another tab's - the message is said only while the record
// names an earlier one (checkDocUpdate) - and stays: that tab read the history too, perhaps after a commit this message
// missed.
function docUpdateSeen(doc: string, update: any) {
  const was = seenDoc(doc);
  if (!was || was.ver !== update.ver) setSeenDoc(doc, { ver: update.ver, rev: update.top });
  forgetUpdate(doc);
}
// What this tab kept for a seen change of a document - its moved pins and its tinted lines - goes. Moves that come
// after this belong to no message that is due (countPinMove).
function forgetUpdate(doc: string) {
  UPDATE_STATE.moved.delete(doc);
  UPDATE_STATE.seenAt.set(doc, Date.now());
  if (UPDATE_STATE.lines.delete(doc)) tintChangedLines();
}
// A source or a build is changing (documents/flow-polling.ts): for UPDATE_EXPECT_MS its pins' moves wait for its
// document's update message. fresh: a source changed now - the wait starts now, so a message seen before it does not
// end it (countPinMove).
function expectUpdate(fresh?: boolean) {
  const now = Date.now();
  if (fresh || UPDATE_STATE.expect < now) UPDATE_STATE.expectAt = now;
  UPDATE_STATE.expect = now + UPDATE_EXPECT_MS;
}
// A pin moved its lines (lost: lost its place) - counted for its document's update message while that stands or is due,
// and said there. Due: a change is awaited (expectUpdate) that this document's message has not been seen for since -
// after [x] on that message a late move (a maintenance save of the moved place, ADR-0028) is said on its own, not taken
// into a message that has gone. Returns whether a moved pin is said there (its own message is then left out); a lost
// pin is always said on its own as well, for it asks for a new place.
function countPinMove(pin: Pin, lost: boolean): boolean {
  const doc = pdoc(pin),
    group = GROUPS.get('upd:' + doc),
    now = Date.now();
  if (!group && !(UPDATE_STATE.expect >= now && (UPDATE_STATE.seenAt.get(doc) || 0) < UPDATE_STATE.expectAt))
    return false;
  let moves = UPDATE_STATE.moved.get(doc);
  if (!moves) {
    moves = { moved: new Set(), lost: new Set() };
    UPDATE_STATE.moved.set(doc, moves);
  }
  (lost ? moves.lost : moves.moved).add(pin.id);
  if (group) groupRedraw('upd:' + doc);
  return !lost;
} // on the line, gathered or folded: it says the move there
// The changes view on the commits the message named, on `doc`: its source diff of base (the last seen commit) → top
// (the newest it named - the shown build's, not the checkout's newest: a checkout ahead of the pages, or a commit come
// since the message, is not in it), the list painting just them (revisions/flow.ts REVISION_VIEW.want); without base,
// the view as it opens. Another document is switched to first.
function openUpdateRange(doc: string, base: string, top?: string) {
  const go = () => {
    REVISION_VIEW.want = { base, top: top || '' };
    REVISION_VIEW.target = null; // the view opened for a pin shows the message's range now, not that pin's commit
    if (document.body.classList.contains('revision-open')) loadRevisions();
    else setViewMode(VIEW_MODE.REVISIONS);
  };
  if (doc === DOC) {
    go();
    return;
  }
  const opening = switchDoc(doc),
    visit = SWITCHSEQ;
  opening.then(() => {
    if (DOC === doc && visit === SWITCHSEQ) go();
  });
}

// ---------------- A drawn document's changed lines
// The source of drawn document `doc` was drawn (markdown/view.ts buildMarkdownDoc); before: the lines it replaced on
// screen (null on the visit's first draw). The lines that differ from the base - the lines before the change not yet
// seen began, kept while its message stands - are tinted (md-upd) while that message stands, and the message says how
// many places and goes to them. A later change before it is seen is compared with that base again, not with the lines
// just drawn, so a place changed first stays tinted and counted beside the new one; a return to the document compares
// what it draws now. A change this device has seen already - its message dismissed while the document was off screen,
// or in another tab - is no base: the lines it drew are not compared, so no tint stands that no message would take
// away.
function compareRedrawnSource(doc: string, before: string[] | null, now: string[]) {
  const changed = UPDATE_STATE.lines.get(doc),
    seen = seenDoc(doc),
    current = shownDocState(doc);
  const base = changed ? changed.base : before && seen && current && verAfter(current.ver, seen.ver) ? before : null;
  // the first draw of a visit asks too: a change that came between the page's meta and this draw made the boot's check
  // give up (its version no longer the one on screen), and nothing else would ask until the next change
  if (!base) {
    checkDocUpdate(doc, {});
    return;
  }
  const ranges = lineChanges(base, now, LINE_DIFF_MAX);
  if (!changed && !ranges.length) return;
  const same = !!changed && JSON.stringify(changed.ranges) === JSON.stringify(ranges);
  UPDATE_STATE.lines.set(doc, { base, ranges, at: changed && same ? changed.at : -1 });
  tintChangedLines();
  if (before) {
    checkDocUpdate(doc, {});
    return;
  }
  if (!same) groupRedraw('upd:' + doc);
} // its message says the places, on the line, gathered or folded
// Tints the changed lines of the document on screen (after every draw of it, markdown/view.ts showDocumentNode), and
// only those.
function tintChangedLines() {
  $$('#md .md-upd').forEach((line) => line.classList.remove('md-upd'));
  const changed = UPDATE_STATE.lines.get(DOC || '');
  if (!changed || !isMarkdownDoc()) return;
  changed.ranges.forEach((range) => lineLeaves(range.lo, range.hi).forEach((line) => line.classList.add('md-upd')));
}
// [바뀐 곳]: the next changed place (the first after the last), scrolled to the reading depth and flashed like a pin's
// lines (showLines: the reading spot is read where it lands).
function goToNextChange(doc: string) {
  if (doc !== DOC) {
    switchDoc(doc);
    return;
  }
  const changed = UPDATE_STATE.lines.get(doc);
  if (!changed || !changed.ranges.length) return;
  changed.at = (changed.at + 1) % changed.ranges.length;
  const range = changed.ranges[changed.at],
    leaves = lineLeaves(range.lo, range.hi);
  if (leaves.length) showLines(leaves);
}

// ---------------- Others' new pins
// Each pin snapshot (pins/flow-list.ts applyPinLists): pins others made since the highest number this tab - or, on the
// first snapshot, this device (limnSeen.pin) - had seen, one message per document. The first visit of a device says
// nothing.
function noteNewPins(rows: Pin[]) {
  const me = (META && META.me && META.me.login) || '',
    max = (rows || []).reduce((highest, pin) => Math.max(highest, pin.id), 0);
  // the highest this device has seen stands even when the pins above the list's highest were deleted since: one
  // restored later keeps its number, and it is no new pin
  if (UPDATE_STATE.top === null) {
    const seen = seenPin();
    UPDATE_STATE.top = Math.max(max, seen === null ? 0 : seen);
    if (seen === null || seen >= max) {
      setSeenPin(max);
      return;
    }
    announceNewPins(freshPins(rows, seen, me));
    return;
  }
  const fresh = freshPins(rows, UPDATE_STATE.top, me);
  UPDATE_STATE.top = Math.max(UPDATE_STATE.top, max);
  if (fresh.length) announceNewPins(fresh);
  else if (![...GROUPS.keys()].some((key) => key.startsWith('new:'))) setSeenPin(UPDATE_STATE.top);
}
function announceNewPins(pins: Pin[]) {
  const by = new Map();
  pins.forEach((pin) => {
    const doc = pdoc(pin);
    if (!by.has(doc)) by.set(doc, []);
    by.get(doc).push(pin);
  });
  if (!pins.length) {
    setSeenPin(UPDATE_STATE.top || 0);
    return;
  }
  by.forEach((list, doc) =>
    groupNote(
      'new:' + doc,
      {
        doc: doc,
        pins: list.map((pin) => ({
          id: pin.id,
          who: who(pin.author) || translate('누군가'),
          verdict: pin.verdict || '',
          place: pin.page
            ? translateTemplate('{n}쪽', { n: pin.page })
            : typeof pin.lo === 'number'
              ? 'L' + pin.lo
              : '',
          note: String(pin.note || '')
            .split('\n')[0]
            .slice(0, 40),
        })),
      },
      newPinsView,
      (older, newer) => ({
        doc: older.doc,
        pins: [...older.pins, ...newer.pins.filter((x: any) => !older.pins.some((y: any) => y.id === x.id))],
      }),
    ),
  );
}
// What a document's new-pins message says: one pin by its number, who made it, where and the start of its memo ('새 핀
// #14 — Bob Park · 3쪽 · 서론 첫 문장…', a verdict pin '새 판정 #15 — … · 채택'); more as a count with their numbers
// and makers. Another document's names it ('부록에 새 핀 2개'). [보기] opens the first; on this document it marks [핀
// N].
function newPinsView(news: any) {
  const here = news.doc === DOC,
    pins = news.pins,
    one = pins.length === 1,
    first = pins[0],
    info = docInfo(news.doc),
    name = info ? info.name : news.doc;
  const head = one
    ? translateTemplate(first.verdict ? '새 판정 #{id}' : '새 핀 #{id}', { id: first.id })
    : translateTemplate('새 핀 {n}개', { n: pins.length });
  const description = one
    ? [first.who, first.place, first.verdict || first.note].filter(Boolean).join(' · ')
    : pins
        .slice(0, 3)
        .map((x: any) => '#' + x.id)
        .join(', ') +
      (pins.length > 3 ? ' ' + translateTemplate('외 {n}개', { n: pins.length - 3 }) : '') +
      ' · ' +
      [...new Set(pins.map((x: any) => x.who))].slice(0, 2).join(', ');
  return {
    msg: (here ? head : translateTemplate('{doc}에 {what}', { doc: name, what: head })) + ' — ' + description,
    kind: NOTICE_KIND.INFO,
    act: { label: here ? '보기' : '열기', tip: '그 핀으로 갑니다', fn: () => openPinFromLink(news.doc, first.id) },
    o: {
      literal: true,
      back: !here,
      dot: here ? NOTICE_DOT.SIDE : '',
      keys: pins.map((x: any) => 'new:' + x.id),
      brief: translateTemplate('새 핀 {n}', { n: pins.length }),
      onEnd: (acted: boolean, seen: boolean) => {
        if ((acted || seen) && ![...GROUPS.keys()].some((key) => key.startsWith('new:')))
          setSeenPin(UPDATE_STATE.top || 0);
      },
    },
  };
}

// ---------------- Limn itself was updated
// The page's version (the [더보기] foot's 'v0.4.51', filled in when the server made the page) and the server's (GET
// /api/version, asked by documents/flow-polling.ts after a lost connection comes back, on return and every
// VERSION_EVERY_MS): when they differ, this tab runs the old viewer against a new server, and the status line says so
// with [새로 고침] until it reloads. A call while one is out (busy) is left to it, and asked again once it is answered
// (again): the one out may fail, or have been answered by the process a restart has just replaced - the return after a
// lost connection must not go unasked.
const VERSION = { page: '', server: '', at: 0, busy: false, again: false };
const VERSION_EVERY_MS = 60000;
function versionDue() {
  return Date.now() - VERSION.at >= VERSION_EVERY_MS;
}
function versionOutdated() {
  if (!VERSION.page) {
    const versionElement = document.querySelector('#more-foot .m-ver');
    VERSION.page = versionElement
      ? String(versionElement.textContent || '')
          .trim()
          .replace(/^v/, '')
      : '';
  }
  return VERSION.server && VERSION.page && VERSION.server !== VERSION.page ? VERSION.server : '';
}
async function checkVersion() {
  if (VERSION.busy) {
    VERSION.again = true;
    return;
  }
  VERSION.busy = true;
  VERSION.again = false;
  VERSION.at = Date.now();
  try {
    const answer = (await api('/api/version', { what: '버전 확인', silent: true })).data,
      version = String((answer && answer.version) || '');
    if (version && version !== VERSION.server) {
      const was = versionOutdated();
      VERSION.server = version;
      if (versionOutdated() !== was) drawStatus();
    }
  } catch (error) {
  } finally {
    VERSION.busy = false;
  }
  if (VERSION.again) checkVersion();
}
// [새로 고침]: reloads this tab - the composer's draft and the reading spot are kept (sessionStorage), what waits
// behind an undo is sent first - unless a reply or an edit is being written, which a reload would lose: that is said
// instead.
function reloadForUpdate() {
  const replyField = REPLY && replyNote(REPLY),
    typing = !!(replyField && replyField.value.trim()) || REPLY_DRAFT.size > 0 || editDirty();
  if (typing) {
    lineNote('쓰던 답글이나 수정이 있습니다 — 보내거나 저장한 뒤 새로 고치세요', NOTICE_KIND.WARN, null, {
      source: 'reload-typing',
      digest: false,
    });
    return;
  }
  flushDeferred();
  location.reload();
}
export {
  DIGEST_TAIL_MS,
  awayTitle,
  checkDocUpdate,
  checkDocsSeen,
  checkVersion,
  reloadForUpdate,
  expectUpdate,
  tintChangedLines,
  noteNewPins,
  countPinMove,
  compareRedrawnSource,
  versionDue,
  versionOutdated,
  visitedBefore,
};
