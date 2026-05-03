#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERLAY_TITLE="kitty-cli-display-image"
BORDER=2

usage() {
  cat >&2 <<'EOF'
Usage: display.sh <image_path>
       display.sh --dismiss

Display an image in a fixed Kitty overlay window, centered with a 2-cell
border on its long axis. Press any key inside the overlay to dismiss, or
run "display.sh --dismiss" from outside.

Requires: kitty terminal with remote control enabled (set
"allow_remote_control yes" and "listen_on unix:/tmp/kitty-{kitty_pid}" in
kitty.conf, then restart kitty).

Options:
  --dismiss    Remove the currently displayed image
  -h, --help   Show this help
EOF
  exit 1
}

require_kitty() {
  if [[ -z "${KITTY_LISTEN_ON:-}" ]]; then
    echo "Error: KITTY_LISTEN_ON is not set." >&2
    echo "Enable kitty remote control in kitty.conf:" >&2
    echo "  allow_remote_control yes" >&2
    echo "  listen_on unix:/tmp/kitty-{kitty_pid}" >&2
    exit 1
  fi
}

dismiss_overlay() {
  kitten @ --to="$KITTY_LISTEN_ON" close-window \
    --match "title:${OVERLAY_TITLE}" >/dev/null 2>&1 || true
}

# Sets IMG_W and IMG_H for the given image path. Uses sips on macOS, falls
# back to format-specific parsing of `file` output for PNG/JPEG/GIF/BMP/TIFF.
get_image_dims() {
  local f=$1 out m w h
  IMG_W=""
  IMG_H=""
  if [[ -z "${IMAGE_DISPLAY_NO_SIPS:-}" ]] && command -v sips >/dev/null 2>&1; then
    out=$(sips -g pixelWidth -g pixelHeight "$f" 2>/dev/null || true)
    IMG_W=$(printf '%s\n' "$out" | awk '/pixelWidth:/ {print $2; exit}')
    IMG_H=$(printf '%s\n' "$out" | awk '/pixelHeight:/ {print $2; exit}')
  fi
  if [[ -z "$IMG_W" || -z "$IMG_H" ]]; then
    out=$(file -b "$f" 2>/dev/null || true)
    case "$out" in
      "PNG image data,"*)
        m=$(printf '%s' "$out" | sed -nE 's/^PNG image data, ([0-9]+) x ([0-9]+).*/\1 \2/p')
        ;;
      "JPEG image data,"*)
        m=$(printf '%s' "$out" | sed -nE 's/.*precision [0-9]+, ([0-9]+)x([0-9]+).*/\1 \2/p')
        ;;
      "GIF image data,"*)
        m=$(printf '%s' "$out" | sed -nE 's/.*GIF image data, version [^,]+, ([0-9]+) x ([0-9]+).*/\1 \2/p')
        ;;
      "PC bitmap"*)
        m=$(printf '%s' "$out" | sed -nE 's/.*PC bitmap[^,]*, [^,]+, ([0-9]+) x -?([0-9]+).*/\1 \2/p')
        ;;
      "TIFF image data"*)
        w=$(printf '%s' "$out" | sed -nE 's/.*width=([0-9]+).*/\1/p')
        h=$(printf '%s' "$out" | sed -nE 's/.*height=([0-9]+).*/\1/p')
        [[ -n "$w" && -n "$h" ]] && m="$w $h"
        ;;
      "RIFF"*"Web/P image"*)
        m=$(printf '%s' "$out" | sed -nE 's/.*Web\/P image.* ([0-9]+)x([0-9]+).*/\1 \2/p')
        ;;
    esac
    if [[ -z "$m" && "$out" == *width=* && "$out" == *height=* ]]; then
      w=$(printf '%s' "$out" | sed -nE 's/.*width=([0-9]+).*/\1/p')
      h=$(printf '%s' "$out" | sed -nE 's/.*height=([0-9]+).*/\1/p')
      [[ -n "$w" && -n "$h" ]] && m="$w $h"
    fi
    if [[ -n "$m" ]]; then
      IMG_W=${m% *}
      IMG_H=${m#* }
    fi
  fi
  [[ -n "$IMG_W" && -n "$IMG_H" ]] && (( IMG_W > 0 && IMG_H > 0 ))
}

overlay_show() {
  local img=$1
  local cols lines ws xpixel ypixel
  cols=$(tput cols)
  lines=$(tput lines)
  ws=$(kitten icat --print-window-size)
  xpixel=${ws%x*}
  ypixel=${ws#*x}
  if ! [[ "$xpixel" =~ ^[0-9]+$ && "$ypixel" =~ ^[0-9]+$ ]] \
    || (( xpixel <= 0 || ypixel <= 0 || cols <= 0 || lines <= 0 )); then
    echo "Error: could not read terminal dimensions" >&2
    exit 1
  fi

  if ! get_image_dims "$img"; then
    echo "Error: could not read image dimensions for $img" >&2
    exit 1
  fi

  local avail_w=$(( cols - 2 * BORDER ))
  local avail_h=$(( lines - 2 * BORDER ))
  if (( avail_w <= 0 || avail_h <= 0 )); then
    echo "Error: terminal too small for image display" >&2
    exit 1
  fi

  # Image dimensions in cells, preserving aspect (cells aren't square).
  local nat_w=$(( IMG_W * cols / xpixel ))
  local nat_h=$(( IMG_H * lines / ypixel ))
  (( nat_w > 0 )) || nat_w=1
  (( nat_h > 0 )) || nat_h=1

  # Cross-multiply to pick the binding axis without floating point.
  local img_cols img_rows
  if (( avail_w * nat_h <= avail_h * nat_w )); then
    img_cols=$avail_w
    img_rows=$(( (avail_w * nat_h + nat_w / 2) / nat_w ))
  else
    img_rows=$avail_h
    img_cols=$(( (avail_h * nat_w + nat_h / 2) / nat_h ))
  fi
  (( img_cols > 0 )) || img_cols=1
  (( img_rows > 0 )) || img_rows=1

  local left=$(( (cols - img_cols) / 2 ))
  local top=$(( (lines - img_rows) / 2 ))
  local prompt_row=$(( top + img_rows + 2 ))
  local prompt_col=$(( left + 1 ))
  (( prompt_row > lines )) && prompt_row=$lines

  kitten icat --place "${img_cols}x${img_rows}@${left}x${top}" --scale-up "$img"
  printf '\e[%d;%dH' "$prompt_row" "$prompt_col"
  printf 'Press any key to dismiss...'
  read -rsn1 || true
}

if [[ $# -lt 1 ]]; then
  usage
fi

case "$1" in
  --dismiss)
    require_kitty
    dismiss_overlay
    exit 0
    ;;
  --overlay-show)
    [[ $# -ge 2 ]] || usage
    overlay_show "$2"
    exit 0
    ;;
  -h|--help)
    usage
    ;;
esac

require_kitty

IMAGE_PATH=$1
if [[ ! "$IMAGE_PATH" = /* ]]; then
  IMAGE_PATH="$(pwd)/$IMAGE_PATH"
fi
if [[ ! -f "$IMAGE_PATH" ]]; then
  echo "Error: File not found: $IMAGE_PATH" >&2
  exit 1
fi

dismiss_overlay
kitten @ --to="$KITTY_LISTEN_ON" launch \
  --type=overlay \
  --title="$OVERLAY_TITLE" \
  --env "IMAGE_DISPLAY_NO_SIPS=${IMAGE_DISPLAY_NO_SIPS:-}" \
  "$SCRIPT_DIR/display.sh" --overlay-show "$IMAGE_PATH" >/dev/null
