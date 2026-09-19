# kitty-cli-display-image

Display an image in a fixed [kitty](https://sw.kovidgoyal.net/kitty/) overlay
window, so an agent can show you a picture in the terminal you are already
working in.

The image is scaled to fit with a 2-cell border and centered. Because it is
drawn in an overlay window rather than inline, it stays put and does not scroll
away with the text underneath it.

## Requirements

kitty with remote control enabled. In `kitty.conf`:

```
allow_remote_control socket-only
listen_on unix:kitty-{kitty_pid}
```

`socket-only` grants exactly what this needs and nothing more: unlike `yes`, it
does not additionally allow programs running inside a kitty window to drive
kitty via terminal escape codes. The socket path is relative on purpose, so
kitty places it in the private per-user temporary directory rather than in
`/tmp`, where the socket would be connectable by any local user.

then **fully restart kitty** — the listening socket is created once per kitty
instance, so opening a new window or tab will not pick up the change. Confirm
it took effect with:

```
echo "$KITTY_LISTEN_ON"
```

That must print a socket path. If it is empty, the script cannot work.

Everything else is either bundled with kitty (`kitten`) or standard POSIX
tooling (`bash`, `stty`, `awk`, `sed`, `file`). `sips` is used on macOS when
available. No Python or Node.

## Usage

```
scripts/display.sh path/to/image.png   # show it
scripts/display.sh --dismiss           # close it
scripts/display.sh --help
```

Any format `kitten icat` understands works, including PNG, JPEG, GIF, BMP,
TIFF, WebP, SVG and PDF.

## How it works

Agent tool calls run with their stdout on a pipe and no controlling terminal,
so a process launched by an agent cannot write graphics escape codes to your
screen directly. The script instead uses kitty's remote control to launch an
overlay window, and re-invokes itself inside that window, where a real terminal
exists.

That split drives the layout: the parent process validates the file and reads
the image dimensions, because a failure there has somewhere useful to go, while
the geometry is computed inside the overlay, which is the only process that
knows the real terminal size.

Vertical centering is the one thing that needs the image's pixel dimensions;
`kitten icat` handles scale-to-fit and horizontal centering on its own. If no
tool on the system can read the dimensions, the image is displayed top-aligned
with a warning rather than refused.

## Portability

`display.sh` is a standalone script. It reads no agent-framework environment
variables and locates itself from `$0`, so any client that can run a shell
command can drive it by absolute path.

## Tests

```
bash tests/test_display.sh
```

Pure bash, no network, and no running kitty instance required — the suite
covers the dimension parsing and the placement geometry, which are the parts
that run before any terminal is touched.
