---
name: kitty-cli-display-image
description: Display an image in the terminal (Kitty graphics protocol). Use this to show images, pictures, graphs, screenshots, and generated images directly in the terminal.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/*)
---

## What I do

I display an image inside a fixed Kitty overlay window. The image is scaled to
fit the terminal with a 2-cell border and centered on both axes. Because the
image lives in an overlay window it stays fixed and does not scroll with the
text underneath it.

## When to use me

- User asks to "show", "display", or "view" an image
- After generating or editing an image, so the user can see the result without
  leaving the terminal
- User wants to preview a screenshot, graph, diagram, or visual asset
- User asks to clear/dismiss a displayed image

## How to use me

### Display an image

```
${CLAUDE_SKILL_DIR}/scripts/display.sh "<path_to_image>"
```

`kitten icat` does the rendering, so any format it supports (PNG, JPEG, GIF,
BMP, TIFF, WebP, SVG, PDF, …) works without conversion.

On success the script prints one line naming the file and its pixel size, and
exits 0. **Check the exit status and relay any stderr to the user.** A non-zero
exit means nothing was displayed. Warnings on stderr mean the image was
displayed with a caveat.

### Dismiss the displayed image

From inside the overlay, the user presses any key.
From outside (e.g. from this agent):

```
${CLAUDE_SKILL_DIR}/scripts/display.sh --dismiss
```

### Behavior

- Only one overlay at a time — launching a new image first dismisses the
  previous one
- The overlay persists until the user dismisses it (any key) or the agent calls
  `--dismiss`
- `--dismiss` closes only the overlay this script opened, identified by the
  window id kitty reported at launch

### Centering and unknown image sizes

Vertical centering needs the image's pixel dimensions, which are read before
the overlay opens (`sips` on macOS, then ImageMagick's `identify`, then
`file`). Horizontal centering and scale-to-fit are handled by `kitten icat`
itself and never depend on this.

When no tool can read the dimensions, the image is **still displayed**, aligned
to the top of the bordered area rather than vertically centered, and a warning
is written to stderr. Relay that warning — the image is on screen, just not
centered.

## Requirements

- **Kitty terminal** with remote control enabled. Add to `kitty.conf`:
  ```
  allow_remote_control socket-only
  listen_on unix:kitty-{kitty_pid}
  ```
  then **fully restart kitty** (a new window or tab is not enough — the
  listening socket is created once per kitty instance). The script reads
  `KITTY_LISTEN_ON` from the environment to reach the running kitty.

  `socket-only` is deliberate: it is all this skill needs, and unlike `yes` it
  does not also let any program running inside a kitty window drive kitty
  through terminal escape codes. The relative socket path is also deliberate —
  kitty resolves it inside the private per-user temporary directory, whereas an
  explicit `/tmp/...` path creates a socket any local user can connect to.
- `kitten` (ships with kitty) on `PATH`, plus standard POSIX tools (`bash`,
  `stty`, `awk`, `sed`, `file`). `sips` is used on macOS when present. No
  Python or Node required.

## Environment variables

- `IMAGE_DISPLAY_NO_SIPS` — on macOS, `sips` is used first to read image
  dimensions. Set this to any non-empty value to skip `sips` and use the
  `identify`/`file` path instead. Useful if `sips` mishandles a format on your
  system, or to exercise the non-macOS code path.

## Error handling

The script reports failures on stderr and exits non-zero. Everything that can
fail is checked before the overlay window opens, so errors reach the caller
rather than disappearing with the window.

| Message | Meaning |
| --- | --- |
| `'kitten' not found on PATH` | kitty's bin directory isn't on `PATH` |
| `KITTY_LISTEN_ON is not set` | Remote control isn't enabled, or kitty wasn't restarted after enabling it (see Requirements) |
| `file not found` / `not a regular file` / `file is not readable` | Check the path |
| `could not determine the dimensions` (warning) | Image is displayed, top-aligned instead of centered |

If the overlay itself hits a problem (terminal too small, `icat` cannot decode
the file), it prints the error in the overlay window and waits for a keypress
so the message stays on screen.

## Portability

`display.sh` is standalone: it reads no agent-framework variables and locates
itself from `$0`, so it can be run by any client, or by hand, using its
absolute path. `${CLAUDE_SKILL_DIR}` above is only how this skill names that
path under Claude Code.
