# Fonts

Self-hosted, so first paint never waits on a third party. Both are SIL Open Font License 1.1 (see `OFL-*.txt`).

| File | Source | Contains |
| --- | --- | --- |
| `manrope-latin.woff2` | Manrope variable, weight 500–700 | Latin, punctuation, **₹** (U+20B9) |
| `fraunces-600-latin.woff2` | Fraunces, static weight 600, optical size 24 | same |

Google's stock "latin" subset omits the rupee sign, which is on nearly every screen, so these are built from the full fonts. To rebuild, download the two `.ttf` files from `github.com/google/fonts/ofl/{manrope,fraunces}` next to `build_subsets.py` and run:

    uv run --with fonttools --with brotli python build_subsets.py

Add a character to `UNI` in the script only if a screen needs it; each addition costs bytes on every first load.
