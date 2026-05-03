---
name: kitty-cli-display-image
description: Display an image in the terminal (Kitty graphics protocol). Use this to show images, pictures, graphs, and generated images directly in the terminal.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/*)
---

## What I do

I display an image inside a fixed Kitty overlay window. The image is sized to
fill the terminal with a 2-cell border on its long axis and is centered on the
short axis, so wide images get vertical centering and tall images get
horizontal centering. Because the image lives in an overlay window it stays
fixed and does not scroll with text underneath.

## When to use me

- User asks to "show", "display", or "view" an image
- After generating an image (e.g., via the image-generation skill)
- User wants to preview a screenshot, graph, or visual asset
- User asks to clear/dismiss a displayed image

## How to use me

### Display an image

```
${CLAUDE_SKILL_DIR}/scripts/display.sh "<path_to_image>"
```

`kitten icat` handles the rendering, so any format it supports (PNG, JPEG,
GIF, BMP, TIFF, WebP, …) works without conversion.

### Dismiss the displayed image

From inside the overlay, the user can press any key.
From outside (e.g., from this agent):

```
${CLAUDE_SKILL_DIR}/scripts/display.sh --dismiss
```

### Behavior

- Only one overlay at a time — launching a new image first dismisses any
  existing one
- The overlay persists until the user dismisses it (any key) or the
  agent calls `--dismiss`

## Requirements

- **Kitty terminal** with remote control enabled. Add to `kitty.conf`:
  ```
  allow_remote_control yes
  listen_on unix:/tmp/kitty-{kitty_pid}
  ```
  then restart kitty. The script reads `KITTY_LISTEN_ON` from the environment
  to talk to the running kitty instance.
- `kitten` (ships with kitty), plus standard POSIX tools (`bash`, `tput`,
  `awk`, `grep`, `file`). On macOS `sips` is used for image dimensions; on
  other systems `file` is the fallback. No Python or Node required.

## Environment variables

- `IMAGE_DISPLAY_NO_SIPS` — on macOS, `sips` is used by default to read image
  dimensions. Set this variable to any non-empty value to skip `sips` and fall
  back to parsing `file -b` output. Useful if `sips` mis-handles a particular
  format on your system, or for testing the non-macOS code path.

## Error Handling

If the script exits non-zero, check stderr. Common issues:
- `KITTY_LISTEN_ON is not set` — kitty remote control isn't configured (see
  Requirements above)
- `File not found` — check the image path
- `could not read image dimensions` — the image format isn't recognized by
  `sips`/`file`; convert to PNG or JPEG and retry
