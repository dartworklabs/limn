# Pin JSON listing VSA implementation plan

- [x] Build a narrow per-run listing context and move list, single, and Trash reads into `features/pins/listing/`.
- [x] Move query parsing and one-pin response; connect guarded routes and remove old flat methods.
- [x] Update direct internal callers and the Handbook current ownership map.
- [x] Differentially compare HTTP and state, run focused and full gates, then commit.
