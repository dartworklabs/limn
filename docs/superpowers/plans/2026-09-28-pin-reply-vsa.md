# Pin reply VSA implementation plan

- [x] Move reply input and answer into the lifecycle feature's HTTP boundary.
- [x] Move the reply transaction into `PinLifecycle`, preserving notice order and the shared reopen notice helper.
- [x] Route reply through the feature, remove the flat application method and empty `service/transitions.py`, and update internal callers.
- [x] Update the Handbook and service package map to match the code.
- [x] Compare HTTP and state files against the prior commit, run focused and full gates, and commit this independent route.
