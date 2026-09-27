"""Shared pin services still behind editing changes (docs/handbook/architecture.md §현재 구조).

Each service loads the pins under the store's lock (PinStore.transact), asks the pure rules in limn.pins (lifecycle,
edit) what happens, writes only when the rule accepts, and then emits the notices and - for the irreversible ones -
the audit line. The outcome goes back as a typed value (a pin state, or the refusal / PinNotFound the HTTP layer
answers in limn.web.answers or a feature HTTP module); nothing here maps an outcome to HTTP.

Modules, one per group of intents that change together:

    context.py      PinContext - what a service needs from the instance - and the typed actor of a request
    add_edit.py     a new pin (line or region) and an edit in place

Pin lifecycle, claim, and Trash actions live in features/pins/.

Nothing here imports server.py or reads its run settings: the composition root (server.pin_context()) makes a
PinContext per call from the store, the clock, the notice and audit sinks, the @-tag lookups, the file locator and
the settings values, so a test that changes a setting or freezes the clock is seen at once.
"""
