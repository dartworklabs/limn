# Pin lifecycle VSA implementation plan

## Goal

Move close, reopen, and confirm into one feature package while preserving their HTTP, storage, and notification behavior.

## Tasks

- [x] Establish focused baseline for parsing, responses, service, access, and HTTP routes.
- [x] Move lifecycle parsing and responses into `features/pins/lifecycle/http.py`; keep shared transport guards in `web`.
- [x] Move close, reopen, and confirm transactions into `features/pins/lifecycle/service.py`; keep the reply transaction in its current owner.
- [x] Bind one lifecycle collaborator per `ServerApplication` and route the three HTTP actions through it. Remove the three flat application methods and update direct internal callers.
- [x] Update Handbook and ADR status to reflect the implemented boundary.
- [x] Run focused and full verification, inspect ownership/imports and diff, then commit the slice.

## Invariants

- Body read, origin, identity, admission, and role checks precede each action.
- Refusal order and HTTP response body stay unchanged.
- `PinStore.transact()` remains the only pin write path; the existing event order remains intact.
- Each application instance uses its own runtime and context.
