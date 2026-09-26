"""@-tags: resolving '@name' in a note, reply or reason to logins, and whom a pin addresses (docs/handbook/api.md
§@태그·사람·이벤트, §담당).

Post text keeps '@name' as-is; only the resolved login is recorded in `mentions`. The candidates come from
limn.people.known_people(). A note save notifies the people it newly tags, at most once per NOTE_MENTION_COOLDOWN_S per
(editor, person, pin) - note_mention_targets() decides that from the recent events.jsonl records the caller reads.

Pure: no files, no clock, no HTTP, no server. Every fact (the people, the records, the time) comes in as an argument.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple, TypeAlias

from limn.pins.edit import ASSIGNEE_AGENT

# A pin record, a thread post or an events.jsonl record as read from JSON.
Row: TypeAlias = Mapping[str, Any]

NOTE_MENTION_COOLDOWN_S = 600      # a note save re-tagging the same person on the same pin notifies them at most this often per editor (issue #10 L3)


def thread_round(r: Row) -> list[Any]:
    """The thread of the currently open round - posts after the last close (ev=close). Everything, if never closed.
    For a reopened pin, starts from (and includes) the reopen reason (ev=reopen) - this is the part an agent
    needs to read when fixing it again. That only applies if the last reopen is after the last close -
    otherwise (still under review, not yet reopened), it's simply everything after the last close. Without
    this distinction, a reply posted during review (between close and reopen) leaked into the new round after
    reopening as a defect (e.g. that reply's @-tags incorrectly ended up in the new round's addressed_to)."""
    th: list[Any] = r["thread"] if isinstance(r.get("thread"), list) else []
    last_close = max((i for i, m in enumerate(th) if isinstance(m, dict) and m.get("ev") == "close"), default=-1)
    last_reopen = max((i for i, m in enumerate(th) if isinstance(m, dict) and m.get("ev") == "reopen"), default=-1)
    start = last_reopen if last_reopen > last_close else last_close + 1
    return [m for m in th[start:] if isinstance(m, dict)]


def mention_tokens(people: Mapping[str, Row]) -> list[tuple[str, set[str]]]:
    """(text, {login...}) - longest first. Full name, login, the part of the login before @, and the first word of the name (multiple logins if they collide)."""
    toks: dict[str, set[str]] = {}
    for login, p in people.items():
        name = str(p.get("name") or "")
        for t in {name, login, login.split("@")[0]} | ({name.split()[0]} if len(name.split()) > 1 else set()):
            if len(t) >= 2:
                toks.setdefault(t.lower(), set()).add(login)
    return sorted(toks.items(), key=lambda kv: -len(kv[0]))


def resolve_mentions(text: object, people: Mapping[str, Row], hints: Iterable[str] | None = None,
                     exclude: str | None = None) -> list[str]:
    """Resolves '@name' to a login (post text is left unchanged). Skipped if the character before '@' is
    alphanumeric (an email address); treated as a different word if an ASCII letter immediately follows a
    name ending in an ASCII letter (@Alicex). A Korean particle attached right after ('@서준님') is fine.
    When a token matches multiple people (same first word of the name), only those in the viewer-selected
    hints are included. Returned in first-seen order, no duplicates. `exclude` (usually the author's own
    login) is removed from the result - so self-@-tagging never turns into "a pin that called someone" /
    "I was called" (observed: a self-mention was picked up as addressed)."""
    return list(dict.fromkeys(mention_hits(text, people, hints, exclude)))


def mention_hits(text: object, people: Mapping[str, Row], hints: Iterable[str] | None = None,
                 exclude: str | None = None) -> list[str]:
    """Every resolved '@name' occurrence in text, in order and with repeats (resolve_mentions() is its de-duplicated
    form). Counting occurrences is what tells a note edit that *adds* another '@Bob' apart from one that only
    fixes a typo next to an existing '@Bob' (note_tags)."""
    text = str(text or "")
    if "@" not in text or not people:
        return []
    low, toks, hint_set = text.lower(), mention_tokens(people), set(hints or ())
    found = []
    for i, ch in enumerate(text):
        if ch != "@" or (i > 0 and (text[i - 1].isalnum() or text[i - 1] in "._-")):
            continue
        rest = low[i + 1:]
        for tok, logins in toks:
            if not rest.startswith(tok):
                continue
            nxt = rest[len(tok):len(tok) + 1]
            if nxt and tok[-1].isascii() and tok[-1].isalnum() and nxt.isascii() and (nxt.isalnum() or nxt == "_"):
                continue
            pick = logins if len(logins) == 1 else logins & hint_set
            for lg in sorted(pick):
                if lg != exclude:
                    found.append(lg)
            if pick:
                break
    return found


def pin_mentions_all(r: Row) -> list[str]:
    """Every person called out on this pin (note + the entire thread)."""
    out = list(r.get("mentions") or [])
    for m in r.get("thread") or []:
        for lg in m.get("mentions") or []:
            if lg not in out:
                out.append(lg)
    return out


def round_mentions(r: Row) -> list[str]:
    """The note's @-tags plus @-tags in the current round's (thread_round) thread posts - shared material for addressed_to/fyi_mentions_to."""
    out = list(r.get("mentions") or [])
    for m in thread_round(r):
        for lg in m.get("mentions") or []:
            if lg not in out:
                out.append(lg)
    return out


def addressed_to(r: Row) -> list[str]:
    """Is this a pin that **asked** a person something - only meaningful for a question pin (kind_req=question). pins.md marks it
    '→ @name', and an agent skips it (unless the requesting user says otherwise). A fix pin's @-tags are just
    for reference, not something a person must answer to close it, so they don't go here - fyi_mentions_to()
    handles those instead (observed: a fix pin that FYI-tagged someone was picked up as '→ @name' and an agent
    skipped it forever). A closed-then-reopened pin doesn't count posts from the old round (thread_round)."""
    a = r.get("assignee")
    if a:                                   # a pin with an assignee: if it's a person, it was handed to them; if it's the agent, no one was called
        return [] if a == ASSIGNEE_AGENT else [a]
    if r.get("kind_req") != "question":
        return []
    return round_mentions(r)


def fyi_mentions_to(r: Row) -> list[str]:
    """People called for reference on a fix pin (kind_req != question) - never skipped, only shown in pins.md as '참고 @name'.
    The opposite of addressed_to() (non-question pins). On a pin with an assignee, every @-tag other than the assignee is FYI."""
    if r.get("assignee"):
        to = addressed_to(r)
        return [lg for lg in round_mentions(r) if lg not in to]
    if r.get("kind_req") == "question":
        return []
    return round_mentions(r)


def note_mention_targets(added: Sequence[str], recent: Iterable[Row], by: str | None, pin: object, now: float,
                         window: float = NOTE_MENTION_COOLDOWN_S) -> list[str]:
    """Which of `added` (people a note save newly tags, in order) get a mention event - the cooldown of issue #10 L3.

    A person is left out when `by` already sent them a note mention about the same pin in the last `window` seconds
    before `now`: toggling '@Bob' off and on through note edits would otherwise notify Bob on every edit. The key is
    (actor login, target login, pin id). Only note mentions count - `mention` records without `msg`; replies and reopen
    reasons carry their thread message id and keep notifying every time, since they leave a visible entry. A suppressed
    mention is never written, so the window runs from the last one sent. A record counts when its `ts` lies less than
    `window` from `now` on either side - events.jsonl rounds ts to milliseconds, so the last mention can read as a
    moment ahead of the next save, and after the clock steps back a far-future record must not silence anyone for
    longer than the window. Records without a numeric ts are ignored. Pure: `recent` (events.jsonl records) and `now`
    (epoch seconds) come from the caller."""
    cooled: set[str] = set()
    for e in recent:
        if e.get("type") != "mention" or "msg" in e or e.get("pin") != pin:
            continue
        if (e.get("by") or {}).get("login") != by:
            continue
        ts = e.get("ts")
        if isinstance(ts, (int, float)) and not isinstance(ts, bool) and abs(now - ts) < window:
            cooled.update(e.get("to") or [])
    return [lg for lg in added if lg not in cooled]


class NoteTags(NamedTuple):
    """What a note save means for @-tags: the note's resolved tags (the pin's mentions) and whom to notify now."""
    mentions: tuple[str, ...]
    notify: list[str]


def tag_note(note: str, old_note: str, people: Mapping[str, Row], hints: Sequence[str] | None,
             me: str | None) -> NoteTags:
    """The saved note's @-tags and the people this save newly tags, before the cooldown.

    mentions is the note's resolved tags (first-seen order, without `me`); notify is everyone whose '@name' occurs more
    often in the new note than in old_note (the note before this edit; empty for a new pin). A typo fix next to an
    existing '@Bob' tags nobody new, while an edit or note_append that writes '@Bob' again does, even though the note
    already tagged him. The caller narrows notify with note_mention_targets() - reading the recent events only when
    notify is not empty."""
    hits = mention_hits(note or "", people, hints, exclude=me)
    before = Counter(mention_hits(old_note or "", people, hints, exclude=me))
    new = list(dict.fromkeys(hits))
    counts = Counter(hits)
    return NoteTags(tuple(new), [lg for lg in new if counts[lg] > before[lg]])
