# Revision PDF zoom implementation plan

> Execute inline using superpowers:executing-plans.

**Goal:** Implement issue #161's approved comparison PDF zoom, pan and fit controls.
**Spec:** `docs/superpowers/specs/2026-10-03-revision-pdf-zoom-design.md`
**Architecture:** Keep comparison state, input and PDF.js rendering in the existing viewer slice, independent of manuscript preferences.
**Stack:** Classic JavaScript/JSDoc, CSS, PDF.js, Python/Playwright.

## Global Constraints

No dependencies, server/API/storage changes or manuscript zoom preference writes. Keep 50–500% bounds, 1.2 steps, pointer anchoring, cancellable rendering and bounded canvases. English code, Korean Handbook. Real browser tests use ready comparison caches and actual PDF.js. No arbitrary sleeps.

## Task 1: Comparison zoom and renderer

**Files:** viewer revisions.js, new revision-zoom.js, parts.txt, revisions.css, index.html, events.js, ui_en.json, tests/test_revision_zoom.py.
**Interfaces:** Existing revision visit sequence and PDF loading lifecycle; new comparison-only ratio, geometry, render generation and controls.

- [x] Write real-PDF browser regressions for fit, buttons, keyboard/wheel, reset/preservation, resize and page reachability; generated ratio invariants.
- [x] Run `uv run pytest -q src/limn/viewer/tests/test_revision_zoom.py`. Expected: missing controls/behavior failures.
- [x] Add controls and renderer with zoom anchors, cancellation, near-page release, resize observation and wheel/touch/Safari input. Wire only active comparison PDF keyboard shortcuts.
- [x] Run focused viewer tests and typecheck. Expected: passing.
- [x] Commit implementation and regression tests.

## Task 2: Documentation and final verification

**Files:** docs/handbook/viewer.md, spec and plan.
**Interfaces:** Document Task 1's actual comparison behavior and limits.

- [x] Update Handbook comparison PDF section.
- [x] Run AGENTS.md verification commands, recording any reproduced pre-existing failures. Expected: no new failures.
- [x] Inspect light/dark and narrow/wide real browser screenshots.
- [x] Commit documentation. The executor then obtains one fresh whole-branch review and fixes material findings with regression tests.

## Review Focus

Check stale loading/render completion after zoom, scope switch or view exit; cancellation promise handling; offscreen page memory; mixed page sizes; unreachable horizontal edges; resize anchors; source tab keyboard routing; two-finger/Safari gesture cleanup; manuscript preference isolation. Confirm no backend contract changes.
