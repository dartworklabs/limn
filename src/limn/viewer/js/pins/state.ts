// ------------------------------------------------ The pin actions in flight, and this tab's own
// What a deferred action keeps while its undo row stands, and the actions this tab made itself, which the pin-change
// messages leave out (pins/flow-actions.ts, pins/flow-changes.ts).
// The pins whose [확인] is out, by id: kept out of every pin snapshot meanwhile (derivePinLists; confirmPin,
// pins/flow-actions.ts).
const CONFIRMING = new Set<number>();
// The pins whose [확인] waits for its undo, by id: off the review list meanwhile, but a page verdict line still counts
// them (verdict/flow-line.ts).
const CONFIRMING_PIN = new Map() as Map<number, Pin>;
// The pins whose [영구 삭제] is out, by id: the Trash leaves them out meanwhile (purgePin, pins/flow-actions.ts).
const PURGING = new Set<number>();
// This tab's own close/drop/reopen/restore already said so where it happened, so the next loadPins()'s notePinChanges
// never announces the same transition again: only the first notePinChanges judgment right after markMine(id) is
// swallowed (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (a
// lost response), it's given up on and later values are announced normally. An action from another tab isn't in this
// map, so it's shown as usual.
const MY_ACTIONS = new Map();
function markMine(id: number | null) {
  MY_ACTIONS.set(id, Date.now() + 10000);
}

export { CONFIRMING, CONFIRMING_PIN, PURGING, MY_ACTIONS, markMine };
