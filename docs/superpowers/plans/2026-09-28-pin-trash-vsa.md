# Pin trash VSA implementation plan

- [x] Move Trash rules and transactions into `features/pins/trash/`, binding one run's context factory without a module-global application.
- [x] Move drop, restore, purge, and clear responses and route entry points; preserve shared guards and remove flat application methods.
- [x] Repoint cleanup, direct internal callers, and current Handbook ownership links; remove `service/trash.py`.
- [x] Compare prior and current HTTP and state files, run focused and full gates, then commit the slice.
