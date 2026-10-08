# Limn native viewer UX comparison

This comparison serves the actual assembled Limn viewer with anonymous sample
data. Both variants use the adopted native card metadata: one quiet line after
the note, neutral 12px text and the original human assignee edit action, tooltip
and resolved identity. Author and reply count remain in the header; meaningful
native badges retain expanded context. The current variant receives native
HTML, CSS, JavaScript, fonts and icons without proposal overrides.

The proposal variant adds direct reading/find controls to the main document top
bar and connects both native note fields to inline @mention autocomplete. Its
candidate assigns the first resolved non-self colleague anywhere in the note;
later colleagues are FYI. With no colleague tag, the existing agent default
remains. Native editing assignment and reply controls retain ownership.
Neither variant contains a PoC status header or scenario navigation. The user
approved only the last assignee/card metadata refinement with “수정시안 적용”.
Main-bar reading/find and the inline assignment candidate remain outside that
approval. Every appearance change, regardless of size, requires presentation of
desktop, mobile, tablet and foldable PoCs before production adoption. Foldable
outside and inside portrait/landscape states are recorded separately. Width-only
screenshots, coarse-pointer emulation and physical-device evidence are distinct.
The current exploration is recorded in the narrowly named 2026-10-08
native-reading-inline-assignment spec/plan/review under `docs/superpowers/`.

From the repository root:

```sh
uv run python tools/ux-poc/serve.py --port 5174
```

The foreground server listens on loopback port 5174. Select a comparison with
`?variant=current` or `?variant=proposal`.

Use the same viewport for comparison. Reload to reset the sample pins and
preferences. Drafts, preferences and API effects are held only in the tab's
memory. There is no extra reset control in the viewer.

## Persistent Tailnet review

The review host runs this anonymous fixture as the user LaunchAgent
`com.limn.ux-preview`. Its canonical configuration and installer live outside
the product repository, in the host's `dotfiles` machine configuration. The
job starts at login and launchd restarts it after exit; it remains available
after an agent or terminal session ends. It requires the host to stay awake,
the user to remain logged in, and Tailscale to be connected.

On the configured review host:

```sh
preview_machine=$(awk '!/^#/ && NF {print; exit}' "$HOME/.dotfiles-machine")
preview_installer="$HOME/dotfiles/machines/$preview_machine/limn-preview/install.sh"
bash "$preview_installer" --dry-run --start
bash "$preview_installer" --start
launchctl print "gui/$(id -u)/com.limn.ux-preview"
tailscale serve status
```

The installer refuses to replace another job or stop a process already using
5174. Its startup check waits for an HTTP response. Logs are under
`~/Library/Logs/limn-ux-preview*.log`. The configured worktree and its synced
Python environment must remain present.

Tailscale Serve provides HTTPS port 5174 to loopback port 5174. The job derives
the node's exact DNS authority at startup and passes it as `--public-host`;
default foreground use permits only loopback hosts. Serve configuration is
managed outside this repository and retains other services' routes. This
fixture grants read access to its anonymous samples within the Tailnet and
does not use a production Limn instance, owner identity, tokens or manuscripts.

Discover and check the shared review URL instead of storing a machine hostname
in the repository:

```sh
preview_url=$(tailscale status --json | jq -r '"https://" + (.Self.DNSName | rtrimstr(".")) + ":5174/?variant=proposal"')
curl --fail --silent --show-error "$preview_url" >/dev/null
printf '%s\n' "$preview_url"
```

Use the same host and port with `variant=current`. Reviewers need a connected Tailscale device with
permission to reach the review host. Keep the service and Serve route enabled
between review sessions. To intentionally retire this preview, stop only this
job with `launchctl bootout "gui/$(id -u)/com.limn.ux-preview"` and remove only
its route with `tailscale serve --https=5174 off`.

## Review scenarios

| Proposal | Native interaction to try |
| --- | --- |
| Reading and body find | Choose **본문 찾기** or **읽기** directly in the main document top bar. Find `thermal` (two hits on page 2) or `온도` (pages 1 and 2), press Enter/Shift+Enter or arrows, and return to PDF with the draft retained. Reading does not automatically open find. Page 3 contains only a figure and has no extracted text. |
| Pin metadata and assignment | Inspect desktop and collapsed/expanded compact cards. Assignment appears once below the note, with kind and native status context. Human assignment retains the native edit action with hover/focus underline; agent assignment is plain text. Native question/review/claim/location badges and actions retain their meaning when expanded. |
| Inline @mention candidate | Select a region and type a middle-of-note `@` in the panel or desktop selection-local field. Choose a colleague from the native list, then inspect the existing preview and saved native card. `Robin Lee` has two anonymous logins: typing the ambiguous name alone assigns nobody, while autocomplete preserves the chosen login through handoff. Delete the tag, try no tag or self `@Alice`, and inspect the agent default. |

Inspect 1440px desktop, 768/1024px tablets, 390/320px phones and a foldable's
344px outside plus 673–717px inside portrait/landscape states, with pin panel
closed/open and reading/find closed/open. Desktop/tablet keep their existing
main-bar height. The phone's direct topbar tools float over the PDF without
reserving an extra 44px row; its native lower navigation remains the document
selection route. Find opens one transient floating row below those controls.
Measure the overlay's content occlusion as well as the preserved viewport height.

The user rejected pin search/work filters, explicit reply intent, work-start/ETA
controls and separate assignment controls. Those extensions are removed.
Consecutive review and rebuild/location recovery are deferred and removed from
this narrowed proposal; their existing native controls still work. The user confirmed the no-tag
assignment default as **agent**, which matches current behavior. Assignment by
tags anywhere remains a proposed production change. Only this proposal's browser
candidate demonstrates first-colleague assignment and FYI; the current variant
retains native leading-tag inference. The fixture uses the native mention scan
to project selected hints into anonymous saved cards. It establishes interactive
presentation and fixture outcomes, not server-side assignment/storage or reply
parity. No product rule changes merely because this demo can execute a candidate.

Both variants now receive the adopted native card metadata directly, without a
second PoC summary or a duplicated recipient. The human assignee button keeps
its native 24px fine-pointer/44px coarse-pointer hit. Coarse-pointer rows reserve
vertical clearance so that the hit stays away from thread controls. The user's
approval covers this card presentation only. Production assignment rules,
composer assignment controls and other workflows retain their existing behavior.

## What this comparison establishes

The real anonymous three-page PDF is rendered and extracted by bundled PDF.js.
Find and selectable reading use the actual bytes; `native-reading.json` remains
only the authored source-location/selection fixture and PDF generation input.
The PDF contains Korean/English prose, repeated hits, simple math and a textless
figure. Outline, page navigation and selection/card controls are native.
`make-sample.py` records its generation recipe; regeneration needs local TeX,
not a runtime dependency.

Assignment, claim, save, reply, review and rebuilding mutate only seeded browser
data. Revision/diff responses are authored examples; the revision PDF reuses the
sample PDF and does not demonstrate a real latexdiff result. The dedicated server
binds to loopback, serves an explicit resource
allowlist, rejects API reads and all HTTP mutations, and never opens an instance
or manuscript directory. The mock adapter never forwards a write request.

The comparison establishes actual sample extraction, repeated-hit page mapping,
interface placement and fixture interaction. It does not establish real source
mapping, rebuild accuracy, semantic column order, arbitrary CJK/math fidelity,
rotated text, scans/OCR, physical gestures/keyboards or screen-reader usability.
Search highlights whole PDF text items, not individual glyphs. Reading keeps PDF
content-stream order. The on-demand extraction limit is 12 pages, 30,000 items
per page and 200,000 characters; PDF bytes are bounded to 20MiB after download.
No production document service is exposed by this bounded fixture.

`uv run pytest -q tests/tools/test_ux_poc_serve.py` uses the existing repository
browser harness for actual coarse-pointer contexts. The test measures native
bands/overflow/viewport cost and checks page-2 hits, selectable reading and note
hints. These emulations are separate from the parent's width-only native-browser
screenshots and are not physical-device validation.

Production adoption of the other workflow proposals remains subject to user review.
The exploration and review records are under `docs/superpowers/`.
