# Bounded native reading and assignment spike

Scope/exit: [exploration spec](../specs/2026-10-08-native-reading-inline-assignment-poc.md).
This checklist tracks the disposable PoC, not a production implementation plan.

- [x] Preserve native viewer and anonymous fixture isolation; extend the sample
  to real multiple PDF pages and allowlisted fallback images.
- [x] Extract with bundled PDF.js on demand, expose selectable reading, and map
  every repeated find occurrence to its actual page/item bounds.
- [x] Connect the selection-local textarea to existing autocomplete/hints and
  inspect first resolved colleague assignment plus FYI in native previews/cards.
- [x] Keep main-topbar controls within existing geometry, with no permanent
  phone row; prepare desktop/phone/tablet/foldable interactions for review.
- [x] Run meaningful tool checks, preserve raw evidence outside the repo, and
  point the existing persistent preview at the delivery worktree through its
  canonical dotfiles plist and installer without changing routes/auth.
- [ ] Record actual browser evidence and limitations; stop before adoption.
