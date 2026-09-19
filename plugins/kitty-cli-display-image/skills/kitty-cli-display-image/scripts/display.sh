#!/usr/bin/env bash
# display.sh -- show an image in a fixed kitty overlay window.
#
# This script is standalone: it reads no agent-framework variables and locates
# itself from $0, so any client that can run a shell command can drive it.
# Requirements are kitty with remote control enabled, plus POSIX tools.
set -euo pipefail

VERSION="1.1.0"
OVERLAY_TITLE="kitty-cli-display-image"
BORDER=2

# Set by get_image_dims. Declared here so that sourcing this file and reading
# them under `set -u` is safe. get_image_dims must be called directly, not in a
# command substitution, or the assignment is lost with the subshell.
IMG_W=""
IMG_H=""

# Set by read_term_size.
TERM_COLS=""
TERM_ROWS=""

# Where the launched overlay's window id is parked so that a later --dismiss
# can close that window specifically rather than every window whose title
# happens to match.
tmp_dir() {
  local t=${TMPDIR:-/tmp}
  printf '%s\n' "${t%/}"
}

# Keyed on the control socket, which identifies the kitty instance the overlay
# was actually created in. KITTY_PID would read more naturally but is not
# guaranteed to be exported into an agent's subprocess, whereas KITTY_LISTEN_ON
# has to be set for any of this to work at all.
state_file() {
  local key
  key=$(printf '%s' "${KITTY_LISTEN_ON:-default}" | tr -c 'A-Za-z0-9' '-')
  printf '%s/%s.%s.window\n' "$(tmp_dir)" "$OVERLAY_TITLE" "$key"
}

usage() {
  cat <<'EOF'
Usage: display.sh [--no-prompt] <image_path>
       display.sh --dismiss
       display.sh --help | --version

Display an image in a fixed kitty overlay window, scaled to fit with a 2-cell
border and centered. The overlay does not scroll with the text underneath it.

Rendering is done by "kitten icat", so any format it supports works. When the
image's dimensions cannot be determined, the image is still displayed, aligned
to the top of the bordered area instead of vertically centered.

Options:
  --no-prompt  Do not draw the "press any key" hint. A keypress still
               dismisses the image; use this when the caller controls how
               long the image stays up, such as a timed slideshow.
  --dismiss    Close the overlay this script last opened
  -h, --help   Show this help
  --version    Print the script version

Requires kitty with remote control enabled. In kitty.conf:
  allow_remote_control socket-only
  listen_on unix:kitty-{kitty_pid}
then fully restart kitty.
EOF
}

die() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

warn() {
  printf 'Warning: %s\n' "$1" >&2
}

# Resolve this script's own absolute path, following symlinks, so the overlay
# can re-invoke it no matter how it was called.
self_path() {
  local src=${BASH_SOURCE[0]} dir
  while [[ -L $src ]]; do
    dir=$(cd -P "$(dirname "$src")" && pwd)
    src=$(readlink "$src")
    [[ $src == /* ]] || src="$dir/$src"
  done
  printf '%s/%s\n' "$(cd -P "$(dirname "$src")" && pwd)" "$(basename "$src")"
}

require_kitty() {
  command -v kitten >/dev/null 2>&1 \
    || die "'kitten' not found on PATH. It ships with kitty; make sure kitty's bin directory is on PATH."
  if [[ -z ${KITTY_LISTEN_ON:-} ]]; then
    printf 'Error: KITTY_LISTEN_ON is not set, so kitty remote control is unavailable.\n' >&2
    printf 'Add to kitty.conf, then fully restart kitty:\n' >&2
    printf '  allow_remote_control socket-only\n' >&2
    printf '  listen_on unix:kitty-{kitty_pid}\n' >&2
    exit 1
  fi
}

# --- image dimensions -------------------------------------------------------
#
# Dimensions are only needed to center the image vertically: icat's --place
# already scales to fit and centers horizontally on its own. So a failure here
# is a downgrade, never a reason to refuse to display the image.

# sips reports fractional sizes for vector formats ("pixelWidth: 300.000").
# Truncate to an integer and reject anything that isn't a positive number.
normalize_dim() {
  local v=${1:-}
  v=${v%%.*}
  [[ $v =~ ^[0-9]+$ ]] || return 1
  (( v > 0 )) || return 1
  printf '%s\n' "$v"
}

# Parse `file -b` output. Kept separate from the probing so it can be tested
# against captured strings without needing the images themselves.
# Echoes "WIDTH HEIGHT"; returns 1 when the format isn't recognized.
dims_from_file_output() {
  local out=${1:-} w="" h=""
  case $out in
    "PNG image data,"*)
      w=$(printf '%s' "$out" | sed -nE 's/^PNG image data, ([0-9]+) x ([0-9]+).*/\1/p')
      h=$(printf '%s' "$out" | sed -nE 's/^PNG image data, ([0-9]+) x ([0-9]+).*/\2/p')
      ;;
    "JPEG image data,"*)
      w=$(printf '%s' "$out" | sed -nE 's/.*precision [0-9]+, ([0-9]+)x([0-9]+).*/\1/p')
      h=$(printf '%s' "$out" | sed -nE 's/.*precision [0-9]+, ([0-9]+)x([0-9]+).*/\2/p')
      ;;
    "GIF image data"*)
      w=$(printf '%s' "$out" | sed -nE 's/.*GIF image data, version [^,]+, ([0-9]+) x ([0-9]+).*/\1/p')
      h=$(printf '%s' "$out" | sed -nE 's/.*GIF image data, version [^,]+, ([0-9]+) x ([0-9]+).*/\2/p')
      ;;
    "PC bitmap"*)
      # BMP height is negative for top-down bitmaps.
      w=$(printf '%s' "$out" | sed -nE 's/.*PC bitmap[^,]*, [^,]+, ([0-9]+) x -?([0-9]+).*/\1/p')
      h=$(printf '%s' "$out" | sed -nE 's/.*PC bitmap[^,]*, [^,]+, ([0-9]+) x -?([0-9]+).*/\2/p')
      ;;
  esac
  # TIFF, WebP and several others expose "width=N ... height=N" in any order.
  if [[ -z $w || -z $h ]]; then
    if [[ $out == *width=* && $out == *height=* ]]; then
      w=$(printf '%s' "$out" | sed -nE 's/.*width=([0-9]+).*/\1/p')
      h=$(printf '%s' "$out" | sed -nE 's/.*height=([0-9]+).*/\1/p')
    fi
  fi
  # WebP reports a bare "640x480" later in the line. The separator has to be
  # matched with .* rather than [^0-9]*, because the encoding name in between
  # contains a digit ("VP8").
  if [[ -z $w || -z $h ]] && [[ $out == *"Web/P image"* ]]; then
    w=$(printf '%s' "$out" | sed -nE 's/.*Web\/P image.*[^0-9]([0-9]+)x([0-9]+).*/\1/p')
    h=$(printf '%s' "$out" | sed -nE 's/.*Web\/P image.*[^0-9]([0-9]+)x([0-9]+).*/\2/p')
  fi
  [[ -n $w && -n $h ]] || return 1
  printf '%s %s\n' "$w" "$h"
}

# Sets IMG_W and IMG_H. Returns 1 when no prober could read the image, leaving
# both empty. Probers are tried cheapest-first; each is allowed to fail.
get_image_dims() {
  local f=$1 out="" pair="" w="" h=""
  IMG_W=""
  IMG_H=""

  if [[ -z ${IMAGE_DISPLAY_NO_SIPS:-} ]] && command -v sips >/dev/null 2>&1; then
    out=$(sips -g pixelWidth -g pixelHeight "$f" 2>/dev/null || true)
    w=$(printf '%s\n' "$out" | awk '/pixelWidth:/ {print $2; exit}')
    h=$(printf '%s\n' "$out" | awk '/pixelHeight:/ {print $2; exit}')
    if w=$(normalize_dim "$w") && h=$(normalize_dim "$h"); then
      IMG_W=$w
      IMG_H=$h
      return 0
    fi
  fi

  if command -v identify >/dev/null 2>&1; then
    out=$(identify -format '%w %h' "${f}[0]" 2>/dev/null || true)
    if [[ $out =~ ^([0-9]+)\ ([0-9]+)$ ]]; then
      IMG_W=${BASH_REMATCH[1]}
      IMG_H=${BASH_REMATCH[2]}
      (( IMG_W > 0 && IMG_H > 0 )) && return 0
      IMG_W=""
      IMG_H=""
    fi
  fi

  out=$(file -b "$f" 2>/dev/null || true)
  if pair=$(dims_from_file_output "$out"); then
    if w=$(normalize_dim "${pair% *}") && h=$(normalize_dim "${pair#* }"); then
      IMG_W=$w
      IMG_H=$h
      return 0
    fi
  fi

  return 1
}

# --- terminal size ----------------------------------------------------------

# Parse `stty size` output ("ROWS COLS") into "COLS ROWS", which is the order
# the rest of this script uses. Split out so it can be tested without a tty.
parse_stty_size() {
  local out=${1:-}
  [[ $out =~ ^[[:space:]]*([0-9]+)[[:space:]]+([0-9]+)[[:space:]]*$ ]] || return 1
  local rows=${BASH_REMATCH[1]} cols=${BASH_REMATCH[2]}
  (( rows > 0 && cols > 0 )) || return 1
  printf '%s %s\n' "$cols" "$rows"
}

# Sets TERM_COLS and TERM_ROWS from the terminal itself.
#
# tput is not usable here: it reads the window size with an ioctl on stdout, so
# inside `cols=$(tput cols)` the command substitution makes stdout a pipe, the
# ioctl fails, and tput silently reports the terminfo default of 80x24. stty
# reads the same ioctl from stdin, and /dev/tty is explicit about which
# terminal is meant.
read_term_size() {
  local out="" pair=""
  out=$(stty size </dev/tty 2>/dev/null || true)
  pair=$(parse_stty_size "$out") || return 1
  TERM_COLS=${pair% *}
  TERM_ROWS=${pair#* }
  return 0
}

# --- geometry ---------------------------------------------------------------

# compute_geometry IMG_W IMG_H COLS LINES XPIXEL YPIXEL
#
# Echoes "COLS ROWS LEFT TOP" describing the --place rectangle. IMG_W/IMG_H may
# be "-" when unknown, in which case the full bordered area is used and the
# image ends up top-aligned.
#
# The fit is computed in pixels rather than cells. Doing it in cells truncates
# small images to a 1-cell dimension, which throws the aspect ratio away and
# leaves the image badly off-center.
compute_geometry() {
  local img_w=$1 img_h=$2 cols=$3 lines=$4 xpixel=$5 ypixel=$6
  local avail_w=$(( cols - 2 * BORDER ))
  local avail_h=$(( lines - 2 * BORDER ))
  if (( avail_w <= 0 || avail_h <= 0 )); then
    printf 'terminal too small to display an image (%sx%s cells)\n' "$cols" "$lines" >&2
    return 1
  fi

  local cell_w=$(( xpixel / cols ))
  local cell_h=$(( ypixel / lines ))
  if (( cell_w <= 0 || cell_h <= 0 )); then
    printf 'terminal reported an unusable cell size\n' >&2
    return 1
  fi

  local img_cols img_rows
  if [[ $img_w == "-" || $img_h == "-" ]]; then
    img_cols=$avail_w
    img_rows=$avail_h
    printf '%s %s %s %s\n' "$img_cols" "$img_rows" "$BORDER" "$BORDER"
    return 0
  fi

  local avail_px_w=$(( avail_w * cell_w ))
  local avail_px_h=$(( avail_h * cell_h ))
  # Cross-multiply to find the binding axis without floating point, then round
  # the free axis up so the box never crops the image.
  if (( avail_px_w * img_h <= avail_px_h * img_w )); then
    img_cols=$avail_w
    img_rows=$(( (avail_px_w * img_h / img_w + cell_h - 1) / cell_h ))
  else
    img_rows=$avail_h
    img_cols=$(( (avail_px_h * img_w / img_h + cell_w - 1) / cell_w ))
  fi
  (( img_cols > 0 )) || img_cols=1
  (( img_rows > 0 )) || img_rows=1
  (( img_cols <= avail_w )) || img_cols=$avail_w
  (( img_rows <= avail_h )) || img_rows=$avail_h

  printf '%s %s %s %s\n' \
    "$img_cols" "$img_rows" "$(( (cols - img_cols) / 2 ))" "$(( (lines - img_rows) / 2 ))"
}

# --- overlay ----------------------------------------------------------------

# Errors raised inside the overlay would otherwise be invisible: the window
# closes the instant the process exits, taking the message with it. Hold the
# window open so the message can actually be read.
overlay_die() {
  printf '\nError: %s\n' "$1" >&2
  printf 'Press any key to close...'
  read -rsn1 || true
  exit 1
}

# Clear the recorded window id on exit, but only if it still refers to this
# overlay. Replacing one image with another closes the old overlay after the
# new id has been recorded, and an unconditional cleanup would delete it.
clear_own_state() {
  local sf cur
  sf=$(state_file)
  cur=$(cat "$sf" 2>/dev/null || true)
  if [[ -n ${KITTY_WINDOW_ID:-} && $cur == "${KITTY_WINDOW_ID}" ]]; then
    rm -f -- "$sf"
  fi
  return 0
}

overlay_show() {
  local img=$1 img_w=$2 img_h=$3 show_prompt=${4:-1}
  local cols lines ws xpixel ypixel geom

  # icat --place parks the cursor on the image's top-left corner, where it sits
  # blinking over the artwork. The overlay only ever displays, so hide it for
  # the window's lifetime and restore it on the way out.
  trap 'printf "\e[?25h"; clear_own_state' EXIT
  printf '\e[?25l'

  read_term_size || overlay_die "could not read the terminal size"
  cols=$TERM_COLS
  lines=$TERM_ROWS
  ws=$(kitten icat --print-window-size 2>/dev/null || true)
  xpixel=${ws%x*}
  ypixel=${ws#*x}
  if ! [[ $xpixel =~ ^[0-9]+$ && $ypixel =~ ^[0-9]+$ ]] \
    || (( xpixel <= 0 || ypixel <= 0 || cols <= 0 || lines <= 0 )); then
    overlay_die "could not read terminal dimensions"
  fi

  geom=$(compute_geometry "$img_w" "$img_h" "$cols" "$lines" "$xpixel" "$ypixel") \
    || overlay_die "could not compute image placement"
  read -r img_cols img_rows left top <<<"$geom"

  # --stdin no keeps icat from treating a redirected stdin as a second image,
  # which makes --place fail with a confusing "not 2" error.
  kitten icat --stdin no --scale-up \
    --place "${img_cols}x${img_rows}@${left}x${top}" "$img" \
    || overlay_die "kitten icat could not display $img"

  # The keypress is always accepted, so a caller driving a timed sequence can
  # still be interrupted; only the advertisement of it is optional. Printing it
  # when the caller controls the timing would promise an interaction the viewer
  # did not ask for, directly under the image.
  if (( show_prompt )); then
    local prompt_row=$(( top + img_rows + 2 ))
    (( prompt_row > lines )) && prompt_row=$lines
    printf '\e[%d;%dH' "$prompt_row" "$(( left + 1 ))"
    printf 'Press any key to dismiss...'
  fi
  read -rsn1 || true
}

dismiss_overlay() {
  local sf win
  sf=$(state_file)
  if [[ -r $sf ]]; then
    win=$(cat "$sf" 2>/dev/null || true)
    rm -f -- "$sf"
    if [[ $win =~ ^[0-9]+$ ]]; then
      kitten @ --to="$KITTY_LISTEN_ON" close-window --match "id:${win}" >/dev/null 2>&1 || true
      return 0
    fi
  fi
  # No recorded id: fall back to the title so overlays opened by an older
  # version of this script can still be cleared.
  kitten @ --to="$KITTY_LISTEN_ON" close-window \
    --match "title:^${OVERLAY_TITLE}$" >/dev/null 2>&1 || true
}

main() {
  local show_prompt=1
  if [[ ${1:-} == "--no-prompt" ]]; then
    show_prompt=0
    shift
  fi

  if [[ $# -lt 1 ]]; then
    usage >&2
    exit 2
  fi

  case $1 in
    -h|--help)
      usage
      exit 0
      ;;
    --version)
      printf '%s %s\n' "$OVERLAY_TITLE" "$VERSION"
      exit 0
      ;;
    --dismiss)
      require_kitty
      dismiss_overlay
      exit 0
      ;;
    --overlay-show)
      # Internal: runs inside the overlay window, where a real terminal exists.
      [[ $# -ge 4 ]] || { usage >&2; exit 2; }
      overlay_show "$2" "$3" "$4" "${5:-1}"
      exit 0
      ;;
    -*)
      printf 'Error: unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac

  require_kitty

  local image_path=$1
  [[ $image_path == /* ]] || image_path="$PWD/$image_path"
  [[ -e $image_path ]] || die "file not found: $image_path"
  [[ -f $image_path ]] || die "not a regular file: $image_path"
  [[ -r $image_path ]] || die "file is not readable: $image_path"

  # Probe dimensions here, in the caller's process, so that a failure is
  # reported to whoever invoked the script. Inside the overlay it would be
  # swallowed when the window closes.
  local dim_w="-" dim_h="-" size_note="size unknown"
  if get_image_dims "$image_path"; then
    dim_w=$IMG_W
    dim_h=$IMG_H
    size_note="${IMG_W}x${IMG_H}"
  else
    warn "could not determine the dimensions of $image_path; it will be displayed top-aligned rather than vertically centered"
  fi

  dismiss_overlay

  local self win launch_args=()
  self=$(self_path)
  # --self keeps the overlay on the tab this was invoked from rather than
  # whichever tab happens to be active, but it needs KITTY_WINDOW_ID to
  # identify the source window; not every client exports it.
  [[ -n ${KITTY_WINDOW_ID:-} ]] && launch_args+=(--self)

  # The ${a[@]+...} guard is required: bash 3.2, still the system bash on
  # macOS, treats "${a[@]}" on an empty array as an unbound variable under -u.
  win=$(kitten @ --to="$KITTY_LISTEN_ON" launch \
    --type=overlay \
    --title="$OVERLAY_TITLE" \
    ${launch_args[@]+"${launch_args[@]}"} \
    "$self" --overlay-show "$image_path" "$dim_w" "$dim_h" "$show_prompt")

  if [[ $win =~ ^[0-9]+$ ]]; then
    printf '%s\n' "$win" >"$(state_file)"
  else
    warn "kitty did not report an overlay window id; --dismiss will fall back to matching by title"
  fi

  printf 'Displaying %s (%s) in a kitty overlay. Press any key in the overlay to dismiss.\n' \
    "$(basename "$image_path")" "$size_note"
}

# Sourcing this file exposes the pure functions to the test suite without
# running anything.
if [[ ${BASH_SOURCE[0]} != "$0" ]]; then
  return 0
fi

main "$@"
