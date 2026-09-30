# README and repository images

The images the README and the GitHub repository page use. The logo files are copies of the brand source's exports, not
drawn here; the screenshots are of Limn itself.

| File | What it is | Where it comes from |
| --- | --- | --- |
| `brand/wordmark-light.svg` | the wordmark "limn": ink strokes, vermilion pin, for light grounds | `site/figures/logo/wordmark-light.svg` |
| `brand/wordmark-dark.svg` | the same wordmark for dark grounds: cream strokes, the pin stays vermilion | `site/figures/logo/wordmark-dark.svg` |
| `app-light.png`, `app-dark.png` | the viewer, light and dark theme, on a sample paper with three pins (2880 x 1800) | `site/figures/use/app-light.png`, `app-dark.png` |
| `social-preview.png` | the repository's social preview (1280 x 640): the wordmark on the paper ground with the tagline, set in Limn Sans | rendered with Playwright from `brand/wordmark-light.svg` |

The brand source is <https://github.com/dartworklabs/limn-sans>, branch `feat/export-figures`, commit
`0b76e883ffae42c508463cc8ff11309c3fd13986` (`make figures`; the manifest records `dirty: false`). The files here are
copied byte for byte; the SVGs and PNGs hash to:

```
4db19e9d17631a1a26f0d60e58c6e1401146d578b7eb2c7c7cd01bdeaa9beba4  brand/wordmark-light.svg
8c688f882ef38de41566e68c21e79c0d292ad82d6006d8362e06eed7771c596f  brand/wordmark-dark.svg
47818d97158bc5c454d4ed56a16d5b7001220b28da65849d820afc144b4ce934  app-light.png
72ffe49a8b1c87bc6629bbc5272114398add72a3fc8b1c5d24d8a474770caff6  app-dark.png
```

Colours: ink `#15161a`, paper `#fbfaf7`, cream `#f4ede1`, vermilion `#e8452c` (the pin only). Do not redraw or recolour the
wordmark; replace it with a fresh export. The screenshots show a sample paper ("Sample paper", "A. Author"), no real
manuscript. GitHub has no API for the social preview: upload `social-preview.png` under Settings, Social preview.

The Limn logo and name are trademarks of Dartwork and are not covered by the software license
([TRADEMARKS.md](../../TRADEMARKS.md)). A fork must replace `brand/` and `social-preview.png` with its own.
