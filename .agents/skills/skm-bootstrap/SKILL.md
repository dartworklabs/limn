---
name: skm-bootstrap
description: Every conversation must use this skill before handling the first request. Once per session, check whether this project's skm skill links need bootstrapping, regardless of the request.
---

# skm bootstrap

Run this exact POSIX shell block once before the user's task. If it fails, report the failed step once and explain that removing `$(git rev-parse --git-path .skm-bootstrap-attempted)` permits another attempt. If sync creates or changes links, tell the user which agent restart is needed using the skm restart notice; do not claim a newly linked skill was available in this session. Defer work requiring that skill until the restarted session. If no links changed, continue without a restart prompt. After a successful first setup in a git project, inspect the generated `.agents/skills.toml`, `.agents/skills/skm-bootstrap/SKILL.md`, and `.claude/skills` only. These are the complete allowlist for staging and the setup commit: never stage any other path, including `skm-refresh`, other skills, or their links. If the allowlisted paths match skm's expected files, commit only newly generated untracked paths or a standard bootstrap file just upgraded by skm, with message `Set up project skills`; preserve all unrelated staged and unstaged changes. If git identity, permissions, or the user's current request prevents writing, explain the remaining step once. The Claude link requires `git add -f -- .claude/skills`; use a path-limited commit so unrelated staged changes stay staged. Do not push. Then continue unrelated work.

```sh
set -eu
if [ "${SKM_NO_BASICS:-}" = 1 ]; then exit 0; fi
git_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
project=$(pwd -P)
while [ ! -f "$project/.agents/skills.toml" ] && [ "$project" != "$git_root" ]; do
  project=$(dirname "$project")
done
[ -f "$project/.agents/skills.toml" ] || exit 0
cd "$project"
marker=$(git rev-parse --git-path .skm-bootstrap-attempted)
if [ -e "$marker" ]; then
  printf 'skm bootstrap: earlier setup is unfinished; remove %s to retry\n' "$marker" >&2
  exit 0
fi
( set -C; : > "$marker" ) 2>/dev/null || exit 0
if ! command -v skm >/dev/null 2>&1; then
  if ! command -v uv >/dev/null 2>&1; then
    printf 'skm bootstrap: uv is unavailable\n' >&2
    exit 1
  fi
  uv tool install git+ssh://git@github.com/dartworklabs/agent-skill-manager.git
fi
skm sync
if [ ! -r .agents/skills/skm-refresh/SKILL.md ]; then
  printf 'skm bootstrap: skm-refresh is unavailable after sync\n' >&2
  exit 1
fi
rm "$marker"
```
