// A file's part of a source diff: its path and its patch text.
interface RevisionFile {
  name: string;
  text: string;
}

/** Read the new-side line ranges of patch hunks, including the anchor of a deletion. */
function hunkRanges(text: string) {
  const out: number[][] = [];
  for (const match of String(text || '').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)) {
    const start = +match[1],
      count = match[2] === undefined ? 1 : +match[2];
    out.push([start, start + Math.max(count, 1) - 1]);
  }
  return out;
}

function pinFileIndex(files: RevisionFile[], file: string) {
  file = String(file || '');
  let best = -1,
    bestLength = 0;
  files.forEach((entry, index) => {
    const name = entry.name;
    if (name && (file === name || file.endsWith('/' + name)) && name.length > bestLength) {
      best = index;
      bestLength = name.length;
    }
  });
  return best;
}
// A target without lines (a region pin's) touches none.
function touchesPin(files: RevisionFile[], target: RevTarget, slack?: number) {
  const index = pinFileIndex(files, target.file),
    { lo: first, hi: last } = target;
  if (index < 0 || first == null || last == null) return false;
  const reach = slack == null ? 5 : slack;
  return hunkRanges(files[index].text).some(([start, end]) => end >= first - reach && start <= last + reach);
}

export { hunkRanges, pinFileIndex, touchesPin };
