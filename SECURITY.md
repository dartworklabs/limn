# Security

> **Warning:** Never expose Limn beyond loopback without an identity provider in front of it: keep the
> default `127.0.0.1` and share it through a private network you trust (`tailscale serve`), or run it
> behind an authenticating proxy with `--auth trusted-proxy`. Never through `tailscale funnel`.
> The design is [ADR-0002](docs/adr/0002-access-control.md) (Korean).

## Threat model in one paragraph

Since v0.2 Limn decides **who a request is** with an identity provider chosen per instance (`--auth`), and
**what they may change** with roles in `people.json`. `tailscale` (the default, identical to v0.1) trusts the
`Tailscale-User-*` headers that `tailscale serve` adds, and only from a loopback TCP peer; everyone on the
tailnet who reaches the port is a collaborator unless `--allow` or `--members-only` narrows it. `local` treats
every loopback request as the owner — for a single user on their own machine, never exposed. `trusted-proxy`
trusts configured identity headers only from `--trusted-proxies` addresses (oauth2-proxy, Cloudflare Access, …)
and refuses everything else with `401`. Agents authenticate with **API tokens** (`limn token create`, sent as
`Authorization: Bearer`, stored as SHA-256 hashes in a `0600` file, revocable without a restart); a valid token
wins over headers and an invalid one is a `401`, never a fallback. Roles: `viewer` may only read (and run
`/api/pick` / `/api/revision-build`), `agent` may do everything except confirm, `editor` and `owner` everything a
person could in v0.1 (a person without a role is an editor). The server binds `127.0.0.1` by default; a
non-loopback `--bind` refuses to start unless the provider is `trusted-proxy` or `--i-know-this-is-insecure` is
given (which prints a loud warning). The v0.1 rule that a headerless loopback request is the agent still holds
under `tailscale` for compatibility, but is deprecated (`--no-agent-loopback` turns it off) and is always off
under `local`, `trusted-proxy` and on a non-loopback bind.

What the server does defend against:

- DNS rebinding and cross-site requests: `Host` and `Origin` are checked (loopback, `*.ts.net`, and names given
  with `--public-host`; `--no-origin-check` turns this off — use it only if a proxy forwards unexpected values).
- Forged identity headers: they are ignored unless the TCP peer is loopback (`tailscale`) or a configured proxy
  (`trusted-proxy`).
- Path traversal: static files are limited by name to the vendored PDF.js modules and the vendored Pretendard font
  slices and stylesheet: one name in the folder, no subpath, with a suffix the folder serves.
- Reading files that are not manuscript: every route that takes a file name (`/api/snippet`, `/api/overlaps`,
  `/api/asset`, a new pin, an edit's `loc`, a close's `changes`) accepts only files under `--manuscript`, symlinks resolved, and never one
  under a dot-named part of it (`.git`, `.env`, `.ssh`, `.latexmkrc`, …): those hold repository and machine secrets,
  not manuscript text, and a `viewer` could otherwise read `.git/config` through a snippet. The refusal is the one for
  a file outside the manuscript (`400 file_outside_manuscript` / `change_outside_manuscript`).
- The change view and comparison builds (`/api/revisions`, `/api/revision-diff`, `/api/revision-build`,
  `/api/revision-pdf`) show only a document's own registered files: a LaTeX document's manuscript files in its main
  file's folder, a figure document's map, the PDF it names and the files it lists, a Markdown or text document's own
  file. Never a file under a dot-named part of the manuscript, judged from `--manuscript`: startup refuses a document
  whose path or build root has one (`--doc`, `--main`, `limn add`, `limn doc add`), and the history, the diffs and a
  comparison build's snapshots of both commits leave such files out, a figure map that lists one included. Never a
  file of another folder whose name a Git pattern would also match (a folder `paper[1]` is matched as that name). A
  document's files are named by the paths registered at startup. A pin's file and the ranges recorded when it was
  closed are named by the paths stored on the pin, placed under the manuscript root registered at startup without
  asking the tree: a stored path below that root is that path, and a record from a moved or cloned checkout is placed by
  its own `file_rel` (a record without one is not placed, and the change view falls back to inferring the pin's
  blocks or to the whole commit). So a folder replaced by a symlink after startup — to a dot-named folder, another
  folder or another repository — does not change which files they are.
- Images a Markdown document shows: `GET /api/asset?doc=&path=` serves an image of the manuscript tree and nothing
  else ([ADR-0030](docs/adr/0030-markdown-tree-images-and-document-links.md), Korean). It takes only a normalized
  path relative to `--manuscript` with an image suffix (`png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`): a leading `/`, a
  backslash, a control character, an empty, `.`, `..` or dot-named part is refused, not repaired (`400
  bad_asset_path`), and the query is decoded once, so `%252e%252e` is a file name with `%` in it. The path then takes
  the tree check above (links resolved, no dot-named part, not the state folder, a regular file opened no-follow at
  every step). The bytes must start as the suffix's format does — an HTML page named `.png` or text named `.svg` is
  `415 asset_not_image` — and go out as the media type the suffix names, with `nosniff`. A file over 8 MiB is refused
  without being read, and a raster image whose header gives more than 8192 × 8192 pixels is refused before any browser
  decodes it (`413`). Every answer carries its own policy, `default-src 'none'; style-src 'unsafe-inline';
  img-src data:; sandbox; frame-ancestors 'none'`: the viewer draws an image only as `<img>`, where an SVG runs nothing
  and loads nothing, and an SVG opened on its own (a new tab, a link to it) is a sandboxed document of an opaque
  origin that runs no script and fetches nothing, so it cannot call Limn's API as the reader. Every answer also
  carries `Cross-Origin-Resource-Policy: same-origin`, so another site cannot embed one to learn whether a file
  exists or how large it is — on a tailnet the reader's identity is attached without a credential the browser could
  withhold. The viewer builds the image address itself from the checked path (no document text reaches it), never
  loads a remote or `data:` image (a remote one would tell a third party who opened the document, when and from
  where), and a relative link opens only another registered document or an image of the tree; the allowlist of
  absolute links is unchanged. A `viewer` can read any image of the tree by its path, as it reads any text file of
  the tree through `/api/snippet`: keep files you would not show your readers out of `--manuscript`.
- The state folder is never manuscript. Keep `--state-dir` outside `--manuscript` (the default and `limn add` do). If
  it points inside, under any name, the routes above refuse every file in it the same way — `people.json`,
  `tokens.json` (hashes), `audit.jsonl`, `events.jsonl` and the pin files — also through a link, the build copy leaves
  it out, and the server prints one warning at startup; keep such a folder out of git and file sync. A state folder
  that would hold a served document's main file (the manuscript folder itself, say) refuses to start.
- Roles, identity providers and how a principal was identified are closed types in the code, so a mistyped comparison
  fails the type check; a `people.json` role Limn does not know is a `viewer`.
- An unusable `people.json` fails closed. If it exists but cannot be read or is not a Limn people file (truncated,
  empty, invalid JSON, wrong shape, no read permission), every person identified by a header is a `viewer`,
  `--members-only` admits no one from it (only `--allow` logins, which do not depend on the file), and the server never
  rewrites it — it used to read such a file as empty and replace it with the one visitor, erasing every role including
  the owner's. One warning goes to stderr; once the file is fixed (content or permissions) the roles apply again on the
  next request, without a restart. Tokens and the `--auth local` owner do not read the file and are unaffected. Keeping
  the roles of an earlier good read was rejected: the result would depend on the process's history, and an unreadable
  `tokens.json` likewise accepts no token.
- Clickjacking: every response carries `X-Frame-Options: DENY` and a `Content-Security-Policy` with
  `frame-ancestors 'none'`. Page images and PDFs are `Cache-Control: private`, never kept by a shared cache.
- Scripts and styles injected into Limn's pages: the viewer (`GET /`) and the refusal page a browser sees enforce
  their own Content-Security-Policy, `default-src 'self'; script-src 'self' <hashes>; style-src 'self' <hashes>;
  img-src 'self' https:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none';
  frame-ancestors 'none'`. Inline code runs only if its text matches the SHA-256 of one of the page's own inline
  `<script>` and `<style>` elements (taken per run, after the interface language and the accent are filled in), and
  scripts, styles and other files load only from the same origin: no `'unsafe-inline'`, no `'unsafe-eval'`, no nonce,
  no report endpoint, and no option turns the policy off. So if text written by someone else gets markup into the
  page, an event handler, a `javascript:` URL or a `style` attribute in it is refused, an inline `<script>` or
  `<style>` in it is refused unless its text matches one of the page's hashes, a script or stylesheet from another
  origin does not load, and an injected `<base>`, form, plugin or frame does nothing. The policy narrows what such
  an injection can do; it is not a sanitizer. A `<script>` or stylesheet link that points at a file of this origin
  still runs or applies, and so does an inline `<script>` or `<style>` whose text matches one of the page's hashes,
  whoever inserted it (CSP3 matches a hash by content). Keeping other people's text from becoming markup at all is
  the viewer's job (it builds markup only through escaping templates, docs/handbook/viewer.md), and the policy is the
  wall behind it. The one other origin is an `https:` image, for avatars (`Tailscale-User-Profile-Pic`,
  accepted only as `https://`): whoever chose an avatar URL can see, from the image requests, who opened the viewer
  and when. A dedicated worker runs under its own response's policy, so the viewer starts workers only from its own
  bundled files. An image of the manuscript tree (`/api/asset`) carries its own sandboxing policy (above). Every other
  response (JSON, `pins.md`, PDFs, page images, vendored files) carries `frame-ancestors 'none'` alone. The design is [ADR-0026](docs/adr/0026-viewer-csp.md) (Korean).
- Requests that arrive through `tailscale serve` without identity headers (a `*.ts.net` or `--public-host` Host, e.g.
  tagged devices) are refused (`403`) since v0.2.1 — only a request that names this machine (a loopback Host) and
  carries no proxy header (`X-Forwarded-For/-Host/-Proto/-Port`, `X-Real-IP`, `Forwarded`, `Via`) can be the
  headerless agent. Host alone is not trusted for this: `tailscale serve` routes by the TLS name and passes the
  client's Host through, but always sets `X-Forwarded-For`. `--tailnet-agent` restores the v0.2.0 behaviour, and never
  past `--allow` or `--members-only`. Under `--auth local`, a request that came through a proxy is refused too (the
  owner is whoever sits at this machine).
- `people.json` (logins and roles) is written with mode `0600`, like `tokens.json`; an older file that others can
  write is tightened to `0600` at startup.
- Bulk deletion: `POST /api/clear` (archive and empty every pin) is refused to everyone but the `owner` role and
  needs an explicit confirmation body; it keeps a backup and records who did it (since v0.2.1).

Agents on the machine that serves an instance keep its token in a **token file**,
`~/.config/limn/<instance>.token`, written once by `limn token create <instance> --save`: mode `0600` (folder `0700`),
never in a repository (the command refuses a folder inside a git work tree that does not ignore the file), the
token not printed unless `--print`. They send it with `curl -H "Authorization: Bearer $(cat ~/.config/limn/<instance>.token)"`;
the instance manager's own checks pass it to curl on stdin, only when every process listening on the instance's
port belongs to this account (so another account that grabs the port while the instance is down gets nothing), and
skip a token file that is a symlink, belongs to another account, or is open to group/others. Agents face that same
risk while an instance is down: on a machine other accounts use, keep instances up (the unit restarts on failure) or
check that the port's listener is this account's before sending the token
(`lsof -a -u "$(id -u)" -iTCP:<port> -sTCP:LISTEN`). The server only checks that the file exists (it never reads it) to
tell agents about it in `pins.md`. `limn token revoke` removes the file when it held the revoked token. Once the
agents use the file, set `AGENT_LOOPBACK=0` on that instance: only this account's processes can then act as the
agent. A token expanded with `$(cat …)` is visible on that curl's command line while it runs; on a machine other
accounts use, pipe it instead: `printf 'Authorization: Bearer %s\n' "$(cat <file>)" | curl -H @- …`. The design is
[ADR-0007](docs/adr/0007-agent-token-file.md) (Korean).

What it does not: a `local` or `tailscale` instance trusts every process on the same machine that can reach
loopback. On a shared machine, give agents tokens, turn off the loopback agent, and use `--members-only`. A raw TCP
forwarder that adds no header — `tailscale serve --tcp` or `--tls-terminated-tcp`, `ssh -L`/`-R`, a plain port
forward — is indistinguishable from a local request, so whoever reaches it is the loopback agent (or, under
`--auth local`, the owner). The supported path, `limn add`/`limn start`, only uses `tailscale serve --https`. If you
forward the port any other way, give agents tokens and set `AGENT_LOOPBACK=0` (`--no-agent-loopback`), and do not use
`--auth local`.

## The manuscript repository is trusted code

Limn builds the manuscript with the rights of the account that runs the server. The main build runs
`latexmk -pdf -synctex=1 -interaction=nonstopmode` in a copy of the manuscript **without** `-norc` and without a
sandbox, so a `latexmkrc` / `.latexmkrc` in the repository (Perl) runs as that account, and TeX runs with your
distribution's default shell-escape setting. Whoever can push to the manuscript repository can therefore run code on
the server: with `--git-pull`, a push to the remote `main` is fetched and built within about a minute, with no one
pressing rebuild. Only point Limn at repositories whose pushers you trust, and run it under an account that holds
nothing else worth taking (other repositories' credentials, unrelated token files).

Comparison builds (`/api/revision-build`) are different: they compile past commits inside a `bwrap` sandbox with
`latexmk -norc -no-shell-escape`, with no home directory, source repository or network. Running the main build the
same way (`-norc`, a sandbox) may become an opt-in later; this is a possibility, not a promise, and nothing changes
today — some manuscripts rely on their `latexmkrc`. The details are in
[build-sync.md](docs/handbook/build-sync.md) (Korean).

## Reporting a vulnerability

Please report security issues privately via GitHub's "Report a vulnerability" (Security → Advisories)
on this repository rather than in a public issue. Include the Limn version (`limn version`), how the
instance is exposed, and steps to reproduce. We aim to acknowledge reports within a week.

## Read requests

GET (and any future HEAD implementation) cannot write persistent state or manuscript files, create folders, or schedule writing work. Bounded in-memory caches and bounded Git reads remain allowed after authentication and admission; this does not eliminate read denial of service. Fetch Metadata is not required for pure reads. Logs are outside this promise, with bounded duplicate suppression for read-reachable tracebacks and damaged-pin warnings.

Opening a viewer no longer registers a person or updates their name, photo or seen timestamps. Only a real authorized changing POST records a person. A new reader with no stored row or pin participation is absent from people/mention candidates; an editor appears after their first change, while the owner must explicitly add a viewer with `limn member add`. Existing rows and roles remain intact. Background maintenance runs at startup, every 60 seconds, and within about 2 seconds of a change to a pinned source, a document's main file or the pin registry (a stat-only check). Every GET, HTTP `/pins.md` included, serves the saved pin positions, so the screen, `/pins.md` and the disk `pins.md` agree; after an edit they may lag by the check interval plus one pass (longer on slow or failed passes). A changing POST re-syncs before it checks `base_rev`, so an edit sent from a stale screen is refused, not applied to moved text.
