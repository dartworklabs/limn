# Pin claim VSA implementation plan

- [x] Move claim input and response mapping into `features/pins/claims/`.
- [x] Move claim and unclaim transactions into `PinClaims`; remove the old service and flat application methods.
- [x] Update internal callers and the Handbook's current ownership map.
- [x] Compare the prior commit and current HTTP and state files, run focused and full gates, then commit the slice.
