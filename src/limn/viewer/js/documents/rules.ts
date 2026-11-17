// ------------------------------------------------ The range ladder's levels
// What a ladder's rung applies to: the composer's selection or an edit card.
interface LevelOwner {
  levels?: Rung[];
  score?: unknown;
  lo?: number;
  hi?: number;
  scope?: string | null;
  env?: string | null;
  snippet?: string;
  elSel?: PinElement | null;
}
function levelOf(owner, key) {
  return (owner.levels || []).find((rung: Rung) => rung.level === key || (rung.merged || []).includes(key));
}
// Applies rung `key` to the owner (the composer's selection or an edit card): its lines, scope and source; a figure
// rung also selects its element (elSel), which lines later set in the excerpt keep (setLines).
function useLevel(owner: LevelOwner, key: string | undefined) {
  const rung = levelOf(owner, key);
  if (!rung) return;
  if ('score' in rung) owner.score = rung.score;
  owner.lo = rung.lo;
  owner.hi = rung.hi;
  owner.scope = rung.level;
  owner.env = rung.env || null;
  owner.snippet = rung.snippet;
  if (rung.el) owner.elSel = rung.el;
}
export { levelOf, useLevel };
