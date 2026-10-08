# Approved UX safety repairs

## Authorization and scope

The workflow diagnosis identified a headerless local browser being treated as an agent while still receiving a human-only confirm control, and PDF pin badges that cannot be reached through native keyboard navigation. The user approved proceeding with all diagnosed improvements and required a PoC before confirming changes with a large UX/UI impact. This specification records the independent, narrow repairs authorized for production; larger workflow and layout changes remain in the PoC approval path.

The existing superpowers delegation capability is unavailable in this session, as already established by the coordinating agent. The approved scope and executable plan are recorded here without another approval request or installing skills.

## Current authority and state

- Question: current implementation and approved repair. Role: purpose; path: `docs/handbook/purpose.md`. Viewer behavior is owned by `src/limn/viewer/`; HTTP authority is owned by `src/limn/security/` and pin lifecycle.
- Role: architecture; path: `docs/handbook/architecture.md`. Server authorization, API fields, pin storage and transaction ordering remain authoritative and unchanged.
- Role: topic; paths: `docs/handbook/viewer.md`, `docs/handbook/operations.md`. Agent identities cannot confirm; a headerless loopback browser under default tailscale authentication is an agent, while `--auth local` identifies the local owner as a person. Existing mark badges use an inert `b` element.
- Role: verification; path: `docs/handbook/verification.md`. Browser regressions observe actual rendered controls, handler responses and persisted state; existing server authority tests remain applicable.

## Required behavior and invariants

1. Offer confirm controls only to a person permitted to write, in both review cards and the changes guide. Agent and viewer screens receive appropriate context instead of an action the server refuses. A human editor or local owner retains the existing review/confirm flow.
2. Explain in both READMEs how a local person uses `--auth local` to review. Keep the default tailscale sharing path and explain its headerless loopback identity; do not change authentication defaults.
3. Render each PDF mark badge as a native button with a descriptive accessible name. Tab, Enter and Space navigate to the same card as clicking. Preserve badge geometry, color, touch reach, selection exclusions and pointer behavior.
4. Keep server human-only confirmation, shown-close conflict validation, deferred confirmation, API/pins.md contracts, runtime dependencies and existing uncommitted repairs unchanged.

## Reasons, limits and acceptance

The server remains the authority; removing a refused browser action improves clarity without granting authority. Native buttons provide keyboard behavior without a second custom keyboard implementation. Existing responsive badge styling and design tokens bound the visual change.

Before production edits, real-browser regressions must fail for an agent confirm affordance and keyboard mark activation. After the repair, agent/viewer controls are absent, a human can confirm and the real store records completion, while direct agent confirmation remains 403. Keyboard activation reveals the correct card without creating a selection or changing pins, and existing desktop/touch badge dimensions remain unchanged. Run affected browser/source guards, authority tests, translations, Ruff and viewer typechecking. No physical device or complete browser-engine coverage is claimed.

No new claim, task queue, stale-PDF workflow, onboarding wizard or page layout is included. Those larger UX changes require the user's PoC confirmation.
