# Trust boundary completion

## Authorization and scope

The user requested merging PR #107 and handling all remaining findings after the audit explicitly identified ambiguous input, default-deny registration and capability/path enforcement. This authorizes implementing those findings. The design below makes that scope concrete before implementation; it does not authorize unrelated identity providers, roles, storage migrations or public exposure.

This is an architectural change to existing request boundaries. Apply arch-spec/brainstorming, code-implement (Python, modeling, structure, integration), code-security and code-testing. Preserve normal client requests and all current role permissions. Previously ambiguous requests are intentionally rejected.

## Current authority and state

- purpose: docs/handbook/purpose.md — code/tests define behavior, api.md defines the agent contract.
- architecture: docs/handbook/architecture.md — standard-library runtime, one instance-wide pin store, complete mediation and explicit run resources.
- general: docs/handbook/code-style-roadmap.md — R1–R10; the current implementation limitations are documented.
- contract: docs/handbook/api.md — existing roles, route names, request selection and error reasons.
- verification: docs/handbook/verification.md — behavior, properties, public contract and packaging gates.

## Current invariants

Python 3.10+, no runtime dependencies. Pin writes go through the existing transaction/lock order. Preserve pins.md bytes, legacy records, existing success responses, ordinary role permissions, authentication modes, instance storage and background-job lifecycle. English source/docstrings, Korean Handbook. No new global mutable authority.

## Design and reasons

### Recognize unambiguous requests

Reject duplicate JSON keys at every depth and non-JSON numeric constants with bad_json. Reject repeated decoded query keys (including empty values), invalid escapes and invalid UTF-8 with bad_query; continue ignoring a single empty query value. Reject duplicate singleton framing/security headers, including identical duplicates. Do not treat list-valued forwarding headers as singleton identities. Preserve role-refusal precedence where applicable; parse body/query before recording people or executing a route. An error closes the connection, so trailing request bytes cannot act.

The alternatives were leaving standard-library first/last-wins behavior (fails the stated security rule), or changing every feature parser (unnecessary duplication). A shared transport parser is the narrowest complete boundary.

### Authority as an enforced value

Keep role decisions in access.py as required by the Handbook. Explicitly enumerate current supported operations; an unrecognized route cannot acquire authority even if added to the dispatcher. Preserve existing role-specific refusal reasons and unregistered-route behavior where possible. A per-request immutable authority snapshots verified identity and binds operation, selected target and instance scope. Mutation entry points require the authority and verify scope/action/target before touching the store or scheduling work. Actor dictionaries are attribution projections only. Factories are private and import/source guards supplement Python's non-sealed constructors. Admitted reads retain their common read scope; new read registrations must declare that policy rather than implicitly acquiring write authority.

A typed actor alone would not constrain an effect; duplicating role checks across slices would split policy ownership. The authority value must be consumed at the effect boundary, not just attached to an HTTP DTO.

### Checked manuscript reads

files.py owns a checked manuscript file capability bound to manuscript root/state exclusions. It validates resolved paths and provides the read/stat sink; callers do not regain permission by wrapping an arbitrary string in Path. Propagate through document facts, stored pin location, selection, editing and Markdown projection. Keep pure domain file strings as serialized data; reacquire a checked handle in the effect shell. Refuse hidden/state/outside paths and post-validation symlink replacement. Use descriptor-relative no-follow traversal where needed so an initial resolve alone is not presented as race protection. Trusted state/artifact writes remain at their existing owners.

Do not introduce a cosmetic wrapper for arbitrary Git argument lists. Preserve the audited Git execution adapter; validate request-selected revisions at the feature boundary and retain repository membership checks.

## Verification

Real HTTP rejection/no-write/connection-close cases; role × operation matrix; future registration rejection; wrong action/target/instance authority rejection and immutable attribution; real filesystem traversal/symlink substitution cases; parser properties; domain transition-sequence properties where useful. Observe new tests failing before fixes or via controlled mutation, then restore. Independent review plus full pytest, shell tests, lint/format, typing, package and Handbook gates.

## Conflicts and unknowns

Generic perfect compliance is not a measurable completion criterion. Close concrete findings and report bounded evidence. Do not bulk-document untouched tests: the skills explicitly scope that requirement to authored/changed code. Missing exhaustive interleavings, every possible input and complete absence of defects remain verification limits, not infinite tasks. CI on PR #107 supplies Python 3.10 and TeX evidence missing locally.
