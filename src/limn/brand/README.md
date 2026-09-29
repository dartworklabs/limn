# Limn logo files (vendored)

The Limn logo as the viewer serves and inlines it: the app icon (the letter i - a stem and a vermilion pin - on a
squircle tile) and the wordmark "limn". Nothing here is drawn by this repository. The files are the output of the
brand source, copied byte for byte; `src/limn/mark.py` maps them to routes and inline markup, and
`docs/handbook/viewer.md` §마크와 파비콘 describes where each one appears.

| Item | Value |
| --- | --- |
| Source | <https://github.com/dartworklabs/limn-sans> - `site/limn-brand.js` (`LIMN.icon`, `LIMN.wordmark`) |
| Commit | dartworklabs/limn-sans `main`, commit `f110bb8211c1cc404eced7d56af6f82fd7856edf` (PR #18, merge `ce9288b`) |
| Built by | `make font` once (it writes `site/limn-font.js`), then `make icons`, which runs `cd site && uv run --no-project --with playwright --with pillow python3 tools/build_icons.py` and writes `site/icons/` with its checks passed |
| Tools | Playwright 1.63.0 with Chromium 153.0.8010.12, Pillow 12.3.0 (as `uv run --with` resolved them); a rebuild with these gives the same bytes |
| Copied | the ten files below from `site/icons/`, unchanged; `SHA256SUMS` here is their ten lines of `site/icons/SHA256SUMS` |
| Check | `sha256sum -c SHA256SUMS` in this folder; `tests/test_brand.py` checks the hashes, that the favicons are the pixel drawings and that each SVG parses |

| File | Served or inlined as |
| --- | --- |
| `favicon.ico`, `favicon-dark.ico` | `GET /favicon.ico`, `GET /favicon-dark.ico` - the 16 and 32 px pixel drawings, 뼈종이 (light) and 먹 (dark) |
| `limn-icon-light-16.png`, `limn-icon-light-32.png` | `GET /favicon-16.png`, `GET /favicon-32.png` |
| `limn-icon-dark-16.png`, `limn-icon-dark-32.png` | `GET /favicon-dark-16.png`, `GET /favicon-dark-32.png` |
| `apple-touch-icon.png` | `GET /apple-touch-icon.png` - 180 px, 뼈종이, full-bleed square (iOS rounds it) |
| `limn-icon-light-16.svg`, `limn-icon-light-14.svg` | the inline icon in the top bar (16 px) and the [더보기] label chip (14 px), with that size's optical correction |
| `limn-wordmark-light-20.svg` | the inline wordmark in the help header, 20 px tall |

Only the light SVGs are vendored: the viewer takes their shapes and replaces each brand colour with a class
(뼈종이 tile, 먹 stroke, 주 pin), and its stylesheet paints both themes from the brand tokens.

## Updating

Rebuild in limn-sans with `make icons`, copy the ten files, replace `SHA256SUMS` with their lines from the build's
`SHA256SUMS`, update the commit above, and run `uv run pytest -q tests/test_brand.py`. Do not edit a file here by hand;
the test fails on any byte that differs from `SHA256SUMS`. A new file needs a line in `limn.mark` (`ICON_ROUTES` or
`MARK_SLOTS`) and one in `SHA256SUMS`. A new icon route also needs its path in `access.READ_PATHS` (new paths are
refused by default), a `<link>` in `src/limn/viewer/index.html` (and a `media=` for its colour scheme) and a line in
`tests/test_web.py` `GET_ROUTES`; a new inline slot needs its placeholder in `index.html`.

## Trademark

The Limn logo - the icon and the wordmark in these files - and the name Limn are trademarks of Dartwork
([TRADEMARKS.md](../../../TRADEMARKS.md)). The software license does not cover them. A fork or modified version must
replace these files with its own. The wordmark's letters are outlines of the Limn Sans typeface (limn-sans, SIL Open
Font License 1.1, based on Quicksand), set as a logo; these files are logo artwork, not a font.
