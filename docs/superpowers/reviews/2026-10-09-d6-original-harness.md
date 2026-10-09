# D6 original harness recovered

The harness behind [ADR-0015](../../adr/0015-d6-measured.md)'s figure-pick thresholds was thought lost. It has been recovered, committed as a maintained tool, and replayed on the code ADR-0015 measured and on current `main`. This record states what was recovered, what the replay shows, and where the evidence stops. It changes no picker, threshold or ADR; the only Handbook change is a pointer to the tool. Historical ADR-0015 and the [2026-10-08 audit](2026-10-08-non-ui-measurement-operations.md) stay as written; where the audit says the original 59,492-drag harness "remains unrecovered", this record supersedes that sentence.

## What was recovered, and from where

ADR-0015 cites "the measurement scripts" as its source, but they were never committed. They were recovered from the transcript of the worker session that ran the 2026-10-06 measurement. Recovered as written: the generator and runner (drag model, grid, outcome classification), the table printer and the drag-by-drag comparison of two result files. Also recovered, and not part of the tool: the analysis scripts for the bootstrap interval, tie handling, per-cover utility and plots.

`tools/measure_figure_pick_d6.py` is the generator, runner, table and comparison as one tool with three sub-commands (`measure`, `table`, `compare`). The map and the PDF are arguments, and the worker count is an option that defaults to the machine's CPU count (the session hard-coded 60). `tools/measure_figure_pick.py` remains what it was, a separate reconstructed sample, and its docstring now says so.

The drag generator consumes the random stream as the session's generator did: the same seed string per page, the same order of sampling and of draws. This was checked rather than assumed. On the reference inputs the tool's 59,492 drags equal the recovered generator's drags value for value, and the tool's result files equal the recovered scripts' result files cell for cell (59,492 drags by 169 threshold cells) at both commits below. The tool differs from the recovered scripts only where they were unsafe or inconvenient:

| Difference | Why |
| --- | --- |
| A map the parser rejects is refused with its reason | The session asserted instead |
| A PDF whose `/MediaBox` count differs from the map's page count is refused | The session paired pages and sizes with `zip`, which silently drops the longer side |
| The picker's `COVER_MIN` and `FILL_MIN` are put back after each worker task | The session only ran in worker processes; a test or a caller in-process would otherwise keep the last grid cell |
| A results file gains a `meta` record (seed, map and PDF hashes); `compare` refuses files with different seeds or maps | A pairing is only a comparison when both runs measured the same drags. Files from the session load unchanged |
| `table` prints a count line and a `mean4` row (the unweighted mean of the four single-target kinds); the threshold pairs are options | The four-kind mean is the figure ADR-0015 reports |

## Replay on the code ADR-0015 measured

The inputs are one figure tool's map (24 pages, 22 of them drawable, 3,158 sampled targets; SHA-256 `a380fef5f7afd92535abd03d99416250bb3eb5b6322f32bb801a2c19abec46e6`, the producer map recorded in the 2026-10-08 audit) and its PDF. Neither is in this repository. Commit `38119ca` is the release merge whose picker ADR-0015 measured (`COVER_MIN = 0.6` there; the grid sets both constants per cell). Each row gives the share of its drags, in percent, with each outcome:

```text
59,492 drags / 22 figures / 3,158 targets
group  n  | 0.6/0.5 ok fi co wr no | 0.4/0.5 ok fi co wr no
tight 12632 | 74.0 1.8 5.7 17.9 0.6 | 77.5 2.8 3.9 15.3 0.4
loose-rel 12632 | 19.9 0.1 36.8 36.9 6.3 | 61.6 1.1 13.2 23.0 1.1
loose-px 12632 | 21.3 0.5 32.6 38.2 7.4 | 28.2 1.5 27.1 39.1 4.0
partial 10268 | 74.4 0.0 5.9 18.3 1.4 | 78.2 0.0 4.2 16.8 0.8
mean4 48164 | 47.4 0.6 20.3 27.8 3.9 | 61.4 1.3 12.1 23.6 1.6
span2 11328 | 50.0 29.0 1.6 19.3 0.1 | 37.5 40.5 0.4 21.5 0.0
small 35956 | 43.2 0.1 21.2 32.3 3.2 | 55.9 0.2 15.2 26.9 1.9
medium 8744 | 55.4 1.5 26.3 12.6 4.3 | 79.9 3.6 6.1 9.5 0.8
big 3464 | 52.2 4.3 5.7 25.9 11.9 | 60.9 8.7 0.3 29.3 0.8
```

Columns are correct, finer (a descendant of the target), coarser (a proper ancestor other than the root), wrong (unrelated) and none (the whole figure). For `span2`, ok is the pair's nearest common ancestor and fi is one of the pair. The size rows leave `span2` out.

**This reproduces ADR-0015's table exactly.** The four-kind mean is 47.4 % to 61.4 % correct, coarser answers 20.3 % to 12.1 %, wrong 27.8 % to 23.6 %, the whole figure 3.9 % to 1.6 %; a pair of neighbours picks its common ancestor in 50.0 % and then 37.5 % of drags, and one of the two in 29.0 % and then 40.5 %; large elements are best at 0.4 (60.9 %).

## Replay on the current picker

The same 59,492 drags, run on `main` at `ab81085`:

```text
59,492 drags / 22 figures / 3,158 targets
group  n  | 0.6/0.5 ok fi co wr no | 0.4/0.5 ok fi co wr no
tight 12632 | 87.2 1.8 1.6 8.9 0.5 | 87.0 2.8 0.9 9.0 0.3
loose-rel 12632 | 36.8 0.0 34.7 22.4 6.1 | 78.3 1.0 8.5 11.2 1.0
loose-px 12632 | 23.0 0.4 37.7 31.5 7.3 | 33.2 1.4 30.3 31.1 3.9
partial 10268 | 83.8 0.0 3.0 11.8 1.3 | 85.2 0.0 2.0 12.0 0.8
mean4 48164 | 57.7 0.6 19.3 18.7 3.8 | 70.9 1.3 10.4 15.8 1.5
span2 11328 | 54.2 30.2 2.1 13.3 0.1 | 39.7 45.0 0.4 14.8 0.0
small 35956 | 56.8 0.1 19.6 20.5 3.1 | 68.3 0.2 12.9 16.8 1.8
medium 8744 | 56.0 1.5 27.6 10.7 4.3 | 80.9 3.6 6.5 8.2 0.8
big 3464 | 53.4 3.7 6.2 24.9 11.9 | 62.8 8.0 0.3 28.1 0.8
```

`main` now ships `COVER_MIN = 0.4`, so the right-hand columns are the shipped behaviour and the left-hand columns show what 0.6 would do with today's picker.

Compared drag by drag at 0.4 / 0.5 (`compare`), over the 48,164 single-target drags:

| Measure | `38119ca` | `ab81085` |
| --- | ---: | ---: |
| Drags that picked the intended element | 61.4 % (four-kind mean) | 70.9 % |
| Coarser answers | 12.1 % | 10.4 % |
| Wrong picks | 11,511 of 48,164 | 7,714 of 48,164 |
| Whole figure | 1.6 % | 1.5 % |

**4,758 drags became correct and 117 stopped being correct** (net 4,641). By target size, correct picks went from 55.9 % to 68.3 % for small elements, 79.9 % to 80.9 % for medium and 60.9 % to 62.8 % for large. By kind: tight 77.5 % to 87.0 %, loose-rel 61.6 % to 78.3 %, loose-px 28.2 % to 33.2 %, partial 78.2 % to 85.2 %. A pair of neighbours picks the common ancestor in 39.7 % of drags (37.5 % before) and one of the two in 45.0 % (40.5 %).

| Size and kind | Drags | Correct before to after | Wrong before to after |
| --- | ---: | --- | --- |
| small, tight | 9,240 | 7,214 to 8,375 (78.1 % to 90.6 %) | 1,441 to 661 |
| small, loose-rel | 9,240 | 5,295 to 7,338 (57.3 % to 79.4 %) | 2,450 to 1,029 |
| small, loose-px | 9,240 | 1,248 to 1,810 (13.5 % to 19.6 %) | 4,376 to 3,439 |
| small, partial | 8,236 | 6,328 to 7,051 (76.8 % to 85.6 %) | 1,397 to 895 |
| medium, tight | 2,344 | 1,985 to 1,997 (84.7 % to 85.2 %) | 179 to 171 |
| medium, loose-rel | 2,344 | 1,788 to 1,815 (76.3 % to 77.4 %) | 205 to 161 |
| medium, loose-px | 2,344 | 1,688 to 1,730 (72.0 % to 73.8 %) | 261 to 204 |
| medium, partial | 1,712 | 1,525 to 1,530 (89.1 % to 89.4 %) | 187 to 182 |
| large, tight | 1,048 | 597 to 618 (57.0 % to 59.0 %) | 318 to 305 |
| large, loose-rel | 1,048 | 704 to 738 (67.2 % to 70.4 %) | 250 to 223 |
| large, loose-px | 1,048 | 629 to 656 (60.0 % to 62.6 %) | 307 to 288 |
| **large, partial** | 320 | **180 to 164 (56.2 % to 51.2 %)** | 140 to 156 |

## One regression and one weak spot

**Large elements, partial drags, are the one cell that got worse:** 180 to 164 correct of 320, and wrong picks 140 to 156. Every other cell, including the other three large kinds, improved or held. The [2026-10-08 audit](2026-10-08-non-ui-measurement-operations.md) saw the same direction on its reconstructed sample (large partial targets, 52.99 % to 52.39 % exact). With 320 drags this cell is small, and this replay does not diagnose it.

**Small elements dragged with a margin of a few screen pixels remain the weakest class:** 19.6 % correct (1,810 of 9,240). The rest of these drags pick a parent or a larger neighbouring box (coarser, 38.2 %), an unrelated element (37.2 %) or the whole figure (4.9 %). In the model a margin of 3 to 12 screen pixels can exceed the element's own size, so the element holds a small share of the drag and a larger box that holds more of it wins. That is the model's geometry; the replay does not isolate which rule of the picker decides each case. ADR-0015 says most wrong answers are not repaired by a threshold, and this is the class where the replay shows the most left.

## Limits

- One figure tool's map (22 drawable pages). Another producer's map can behave differently, and ADR-0015 already says to measure again when one appears.
- The drags are modelled, not recorded from people: a fixed scale range of 1.42 to 2.13 px per point, Gaussian edge jitter and four margin models. The results compare pickers on identical drags; they do not measure human accuracy.
- Targets are sampled in proportion to element counts, so thin lines, ticks and small labels dominate. Absolute shares are pessimistic and the paired differences are the usable output.
- Both replays use one seed. The tool reports no confidence interval; the bootstrap analysis of the session was recovered but is not part of the tool.
- A replay needs the original map and PDF. They are not kept in this repository, which holds no figure content; the SHA-256 above identifies the map.
- The drags depend on Python's `random` module. The replay ran on CPython 3.14.6; the tool's tests pin the stream on a made-up map so a change of generator shows up in the test suite.

## Reproduce

With `$MAP` and `$PDF` the reference map and PDF, `$OUT` a scratch directory and `$OLD` a path for a second worktree. Each replay takes under two minutes on a 64-core machine:

```sh
uv run python tools/measure_figure_pick_d6.py measure "$MAP" "$PDF" -o "$OUT/main.json"
git worktree add --detach "$OLD" 38119ca
cp tools/measure_figure_pick_d6.py "$OLD/tools/"
(cd "$OLD" && uv run python tools/measure_figure_pick_d6.py measure "$MAP" "$PDF" -o "$OUT/38119ca.json")
uv run python tools/measure_figure_pick_d6.py table "$OUT/38119ca.json"
uv run python tools/measure_figure_pick_d6.py table "$OUT/main.json"
uv run python tools/measure_figure_pick_d6.py compare "$OUT/38119ca.json" "$OUT/main.json"
```

The copied tool file in the old worktree is not committed there. Its tests, `tests/tools/test_measure_figure_pick_d6.py`, build their own map and PDF and assert the random stream, the outcome classification on hand-checked cases, the table and comparison arithmetic, and the refusals.
