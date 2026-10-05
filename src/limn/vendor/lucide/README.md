# Lucide icons (vendored)

The viewer's icons come from [Lucide](https://github.com/lucide-icons/lucide). Only the SVG elements of the icons in use are inlined as strings in the `LUCIDE` dict of `src/limn/viewer/assemble.py`. The server does not serve icon files and uses no external CDN — the viewer runs inside a private network. This directory holds only the license and provenance record.

| Item | Value |
| --- | --- |
| Package | `lucide-static@1.47.0` (npm `latest`, published 2026-09-17) |
| Repository | <https://github.com/lucide-icons/lucide> |
| Obtained by | `npm pack lucide-static@1.47.0` → copied the elements inside `<svg>` from `package/icons/<name>.svg`. Whitespace was collapsed to single spaces; coordinates are unchanged |
| tarball sha256 | `b47744c9f7b385c25fb27d212cf9830947030a57a635f8b11a5473a72ec57cfd` |
| License | ISC; icons derived from Feather are MIT — [`LICENSE`](LICENSE) (the package's `LICENSE`, unmodified, sha256 `b495047b…29c57`) |

Icons are drawn with the original `<svg>` attributes: `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`, `stroke-linecap="round"`, `stroke-linejoin="round"`. CSS scales them to 14–16px and they follow the text colour.

## Icons in use

| Name | Used for |
| --- | --- |
| `at-sign` | 'mentions me' and '@name' badges, [pins that mention me N] |
| `bell` | the browser notifications switch in [More] |
| `bot` | local/agent avatar (distinct from a person's initial circle) |
| `check` | closed-pin row head; current document in the document list; current page in the page list |
| `chevron-down` · `chevron-right` | collapse/expand archive sections, card collapse (narrow screens), [Documents] button, the page count that opens the page list |
| `chevron-left` | the collapsed wide panel's [Pins N ‹] (#nav-side) |
| `circle-check` · `circle-x` | a message's lead icon (banners, undo rows and chips, the status line) — done/error. Warnings use `triangle-alert` |
| `circle-question-mark` | 'question' badge and hint |
| `message-square` | reply count in the card head |
| `clock` | 'in progress' (claimed) badge |
| `copy` | copy-location button |
| `ellipsis` | the [More] button (every layout) |
| `eye` | 'awaiting review' badge (whose turn it is to confirm) |
| `image` | the status line's 'showing PNG' state (compact bands) |
| `info` | the lead icon of an informational message (a first-visit hint, a restored draft, a conflict with nothing to do) |
| `minus` · `plus` | PDF zoom out/in; shrink/grow a range by one line |
| `moon` · `sun` · `sun-moon` | the theme segments in [More] (dark, light, system) |
| `lock-open` | [풀기] (release the in-progress claim) on a compact card |
| `move-vertical` | 'lines moved +N' badge |
| `move-horizontal` | fit PDF width (desktop toolbar) |
| `panel-left` | open/close the outline (document navigation bar) |
| `pencil` | 'edited' badge; [수정] on a compact card |
| `pin` | the pin panel and sheet toggle on compact bars (the icon before the open count) |
| `refresh-cw` | [Rebuild PDF] |
| `rotate-ccw` | 'reopened' badge (pin sent back from review) |
| `rotate-cw` | [Reload pins] in [More] (compact bands) |
| `square-dashed` | [Select] button and the select mode's bar — a dashed square, symmetric both ways: pick a spot or drag a region on touch devices |
| `trash-2` | deleted-pin row head; [삭제] on a compact card |
| `triangle-alert` | 'location lost' badge, a warning message's lead icon |
| `wifi-off` | the status line's 'disconnected' state (compact bands) |
| `x` | close messages and notices |

## Updating

1. `npm pack lucide-static@<new version>` and copy the elements inside `<svg>` of the icons listed above into `LUCIDE` again. Some icons were renamed (e.g. `alert-triangle` → `triangle-alert`, `help-circle` → `circle-question-mark`); use the new names.
2. Replace `LICENSE` with the new package's and update the version and sha256 above.
3. When adding or removing icons, update `LUCIDE_VERSION`, the table above and `LUCIDE` together. The regression tests (`FrontendIcons`) check that the three agree.
