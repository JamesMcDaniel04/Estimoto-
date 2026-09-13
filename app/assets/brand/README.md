# Estimoto + icon

`estimoto-plus-icon.png` is the selected app artwork: the existing Estimoto white E and teal dot on navy, with a white plus sign centered in the teal dot. The built-in image-generation edit tool produced the artwork from the existing Estimoto app icon on 2026-09-13. It was copied into this repository and packaged at 1024×1024 RGB with no alpha channel.

Edit prompt: “Preserve the existing navy square background (#0D3F7A), the exact white geometric E, and the existing teal circular dot (#00B8A9), all at their current positions and proportions. Add one crisp white plus sign (+) centered inside the existing teal circle. The plus must be clearly legible at small app-icon sizes, with equal-length perpendicular bars, flat ends, balanced spacing, and no outline or shadow. Make only that change; preserve all other artwork, flat colors, edges, and layout. Output a full-bleed square app icon with opaque background, no rounded outer corners, no words, no border, no extra symbols.”

Run `python3 scripts/sync_app_icons.py` from the repository root on macOS to produce native and web sizes with `sips`. The header and welcome screen consume the master asset directly.
