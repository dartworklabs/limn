interface ShownBuild {
  error: BuildStatus | null;
  cur: BuildStatus | null;
  unchanged: { pull: string } | null;
}
const SHOWN_BUILD: ShownBuild = {
  error: null,
  cur: null,
  unchanged: null,
};
function setBuildError(value: BuildStatus | null) {
  SHOWN_BUILD.error = value;
}
function setCurrentBuild(value: BuildStatus | null) {
  SHOWN_BUILD.cur = value;
}
function setBuildUnchanged(value: typeof SHOWN_BUILD.unchanged) {
  SHOWN_BUILD.unchanged = value;
}
export { SHOWN_BUILD, setBuildError, setCurrentBuild, setBuildUnchanged };
