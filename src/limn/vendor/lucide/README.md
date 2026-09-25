# Lucide icons (vendored)

The viewer's icons come from [Lucide](https://github.com/lucide-icons/lucide). Only the SVG elements of the icons in use are inlined as strings in the `LUCIDE` dict of `src/limn/server.py`. The server does not serve icon files and uses no external CDN — the viewer runs inside a private network. This directory holds only the license and provenance record.

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
| `bell` · `bell-off` | browser notifications on/off (desktop toolbar) |
| `bot` | local/agent avatar (distinct from a person's initial circle) |
| `check` | closed-pin row head; current document in the document list |
| `chevron-down` · `chevron-right` | collapse/expand archive sections, card collapse (narrow screens), [Documents] button |
| `chevron-up` · `chevron-left` | direction of opening/closing the [Pins N] panel and sheet |
| `circle-check` · `circle-x` | toast lead icon — done/error. Warnings use `triangle-alert` |
| `circle-question-mark` | help button, 'question' badge |
| `message-square` | reply count in the card head |
| `clock` | 'in progress' (claimed) badge |
| `copy` | copy-location button |
| `ellipsis` | more button (narrow screens) |
| `eye` | 'awaiting review' badge (whose turn it is to confirm) |
| `minus` · `plus` | PDF zoom out/in; shrink/grow a range by one line |
| `moon` · `sun` · `sun-moon` | theme (dark, light, system) |
| `move-vertical` | 'lines moved +N' badge |
| `move-horizontal` | fit PDF width (desktop toolbar) |
| `panel-left` | open/close the outline (document navigation bar) |
| `pencil` | 'edited' badge |
| `refresh-cw` | [Rebuild PDF] |
| `rotate-ccw` | 'reopened' badge (pin sent back from review) |
| `square-dashed` | [Select] button — drag to pick a region on touch devices (same shape as the dashed box on the PDF) |
| `text-wrap` | [Wrap] in the source diff |
| `trash-2` | deleted-pin row head |
| `triangle-alert` | 'location lost' badge, warning toast lead icon |
| `x` | close toasts and notices |

## Updating

1. `npm pack lucide-static@<new version>` and copy the elements inside `<svg>` of the icons listed above into `LUCIDE` again. Some icons were renamed (e.g. `alert-triangle` → `triangle-alert`, `help-circle` → `circle-question-mark`); use the new names.
2. Replace `LICENSE` with the new package's and update the version and sha256 above.
3. When adding or removing icons, update `LUCIDE_VERSION`, the table above and `LUCIDE` together. The regression tests (`FrontendIcons`) check that the three agree.
