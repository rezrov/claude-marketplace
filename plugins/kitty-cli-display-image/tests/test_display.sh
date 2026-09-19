#!/usr/bin/env bash
# Tests for display.sh. Pure bash, no network, no kitty instance required:
# everything here exercises the functions that run before any terminal is
# touched. Run with: bash tests/test_display.sh
set -uo pipefail

SCRIPT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/skills/kitty-cli-display-image/scripts/display.sh"

PASS=0
FAIL=0
FAILED_NAMES=()

ok() {
  PASS=$((PASS + 1))
}

bad() {
  FAIL=$((FAIL + 1))
  FAILED_NAMES+=("$1")
  printf 'FAIL: %s\n' "$1" >&2
  printf '      %s\n' "$2" >&2
}

assert_eq() {
  local name=$1 want=$2 got=$3
  if [[ $want == "$got" ]]; then ok; else bad "$name" "want [$want], got [$got]"; fi
}

assert_ok() {
  local name=$1 status=$2
  if (( status == 0 )); then ok; else bad "$name" "expected success, got exit $status"; fi
}

assert_fail() {
  local name=$1 status=$2
  if (( status != 0 )); then ok; else bad "$name" "expected failure, got exit 0"; fi
}

# shellcheck source=/dev/null
source "$SCRIPT"
# display.sh sets -e for its own use; the assertions below deliberately run
# commands that fail, so turn it back off for the test shell.
set +e

# --- normalize_dim ----------------------------------------------------------
# sips reports vector formats as floats; the old code fed those straight into
# (( )) and died with "arithmetic syntax error".

assert_eq "normalize_dim integer"        "400" "$(normalize_dim 400)"
assert_eq "normalize_dim sips float"     "300" "$(normalize_dim 300.000)"
assert_eq "normalize_dim float non-zero" "150" "$(normalize_dim 150.750)"

normalize_dim "" >/dev/null 2>&1; assert_fail "normalize_dim rejects empty" $?
normalize_dim "abc" >/dev/null 2>&1; assert_fail "normalize_dim rejects text" $?
normalize_dim "0" >/dev/null 2>&1; assert_fail "normalize_dim rejects zero" $?
normalize_dim "-5" >/dev/null 2>&1; assert_fail "normalize_dim rejects negative" $?
normalize_dim "12x34" >/dev/null 2>&1; assert_fail "normalize_dim rejects junk" $?

# --- dims_from_file_output --------------------------------------------------
# Captured from `file -b` on macOS. Parsing is tested against strings so the
# suite doesn't depend on which file(1) version is installed.

assert_eq "png dims" "400 100" \
  "$(dims_from_file_output 'PNG image data, 400 x 100, 8-bit/color RGB, non-interlaced')"

assert_eq "jpeg dims" "400 100" \
  "$(dims_from_file_output 'JPEG image data, JFIF standard 1.01, aspect ratio, density 72x72, segment length 16, Exif Standard: [TIFF image data, big-endian, direntries=1], baseline, precision 8, 400x100, components 3')"

assert_eq "gif dims" "400 100" \
  "$(dims_from_file_output 'GIF image data, version 87a, 400 x 100')"

# BMP stores a negative height for top-down bitmaps.
assert_eq "bmp dims (negative height)" "400 100" \
  "$(dims_from_file_output 'PC bitmap, Windows 3.x format, 400 x -100 x 24, image size 120000, cbSize 120054, bits offset 54')"

# TIFF lists height= before width=, so order must not matter.
assert_eq "tiff dims (reversed order)" "400 100" \
  "$(dims_from_file_output 'TIFF image data, big-endian, direntries=16, height=100, bps=1, compression=none, PhotometricIntepretation=RGB, orientation=upper-left, width=400')"

assert_eq "webp dims" "640 480" \
  "$(dims_from_file_output 'RIFF (little-endian) data, Web/P image, VP8 encoding, 640x480, Scaling: [none]x[none], YUV color, decoders should clamp')"

# Regression: `local m` left m unset, so `set -u` turned any unrecognized
# format into "m: unbound variable" -- a bash crash, not a clean failure.
dims_from_file_output 'SVG Scalable Vector Graphics image' >/dev/null 2>&1
assert_fail "unknown format fails cleanly" $?
dims_from_file_output 'PDF document, version 1.3, 1 pages' >/dev/null 2>&1
assert_fail "pdf without dims fails cleanly" $?
dims_from_file_output '' >/dev/null 2>&1
assert_fail "empty file output fails cleanly" $?

err=$(dims_from_file_output 'SVG Scalable Vector Graphics image' 2>&1 >/dev/null)
assert_eq "unknown format is silent (no bash error)" "" "$err"

# --- get_image_dims ---------------------------------------------------------
# The end-to-end probe must also fail cleanly rather than crashing.

FIXTURE_DIR=$(mktemp -d)
trap 'rm -rf -- "$FIXTURE_DIR"' EXIT

printf 'not an image at all' >"$FIXTURE_DIR/garbage.bin"
IMAGE_DISPLAY_NO_SIPS=1 get_image_dims "$FIXTURE_DIR/garbage.bin" >/dev/null 2>&1
assert_fail "get_image_dims fails cleanly on garbage" $?

err=$(IMAGE_DISPLAY_NO_SIPS=1 get_image_dims "$FIXTURE_DIR/garbage.bin" 2>&1 >/dev/null)
assert_eq "get_image_dims is silent on garbage" "" "$err"

IMAGE_DISPLAY_NO_SIPS=1 get_image_dims "$FIXTURE_DIR/does-not-exist.png" >/dev/null 2>&1
assert_fail "get_image_dims fails cleanly on missing file" $?

# A header-only GIF: file(1) reads dimensions straight from the logical screen
# descriptor, which exercises the file-parsing path without a real encoder.
printf 'GIF89a\x90\x01\x64\x00\x00\x00\x00\x3b' >"$FIXTURE_DIR/tiny.gif"
if file -b "$FIXTURE_DIR/tiny.gif" | grep -q '^GIF image data'; then
  IMAGE_DISPLAY_NO_SIPS=1 get_image_dims "$FIXTURE_DIR/tiny.gif"
  assert_eq "get_image_dims reads gif width" "400" "$IMG_W"
  assert_eq "get_image_dims reads gif height" "100" "$IMG_H"
else
  printf 'SKIP: file(1) did not recognize the GIF fixture\n' >&2
fi

# --- compute_geometry -------------------------------------------------------
# Terminal used below: 200x50 cells at 1800x950px, so cells are 9x19.

assert_eq "wide image binds on width" "196 24 2 13" \
  "$(compute_geometry 400 100 200 50 1800 950)"

# 874px of usable height / aspect 0.5 = 437px wide = ceil(437/9) = 49 cells.
assert_eq "tall image binds on height" "49 46 75 2" \
  "$(compute_geometry 600 1200 200 50 1800 950)"

# Regression: computing the fit in cell space truncated small images to a
# 1-cell dimension, which destroyed the aspect ratio and left a 16x16 image
# roughly 12 rows above where it belonged.
read -r c16 r16 _ t16 <<<"$(compute_geometry 16 16 200 50 1800 950)"
read -r c512 r512 _ t512 <<<"$(compute_geometry 512 512 200 50 1800 950)"
assert_eq "tiny square matches large square (cols)" "$c512" "$c16"
assert_eq "tiny square matches large square (rows)" "$r512" "$r16"
assert_eq "tiny square is centered like a large one" "$t512" "$t16"

# Squares must stay square: 46 rows * 19px = 874px tall, so ~97 cols * 9px.
read -r sc sr _ _ <<<"$(compute_geometry 512 512 200 50 1800 950)"
sq_w=$(( sc * 9 ))
sq_h=$(( sr * 19 ))
delta=$(( sq_w - sq_h )); (( delta < 0 )) && delta=$(( -delta ))
if (( delta <= 9 )); then ok; else bad "square stays square" "box ${sq_w}x${sq_h}px differs by ${delta}px"; fi

# The box must never exceed the bordered area, even after rounding up.
for dims in "400 100" "1920 1080" "3840 2160" "16 16" "1 10000" "10000 1" "7 3"; do
  read -r w h <<<"$dims"
  read -r gc gr gl gt <<<"$(compute_geometry "$w" "$h" 200 50 1800 950)"
  if (( gc >= 1 && gc <= 196 && gr >= 1 && gr <= 46 && gl >= 0 && gt >= 0 )); then
    ok
  else
    bad "geometry stays in bounds ($dims)" "got ${gc}x${gr}@${gl}x${gt}"
  fi
done

# Unknown dimensions: use the whole bordered area, top-aligned at the border.
assert_eq "unknown dims use full area" "196 46 2 2" \
  "$(compute_geometry - - 200 50 1800 950)"
assert_eq "unknown width alone is enough" "196 46 2 2" \
  "$(compute_geometry - 100 200 50 1800 950)"

# Degenerate terminals must be reported, not divided by.
compute_geometry 400 100 4 4 36 76 >/dev/null 2>&1
assert_fail "terminal too small is an error" $?
compute_geometry 400 100 200 50 0 0 >/dev/null 2>&1
assert_fail "zero pixel size is an error" $?

# A very wide terminal where height binds: image must be centered horizontally.
read -r hc hr hl ht <<<"$(compute_geometry 100 400 200 50 1800 950)"
expected_left=$(( (200 - hc) / 2 ))
assert_eq "horizontal centering when height binds" "$expected_left" "$hl"

# --- icat_error_message -----------------------------------------------------
# kitten icat exits 0 even when it cannot decode a file, reporting the problem
# only on stderr. Checking its exit status left the user with a blank overlay
# while the caller was told the image had been displayed.

err_svg='Failed to process logo.svg: Could not render image to RGB: image: unknown format'
assert_eq "decode failure is reported" "$err_svg" "$(icat_error_message "$err_svg")"

icat_error_message "" >/dev/null 2>&1
assert_fail "empty stderr is success" $?
icat_error_message "   " >/dev/null 2>&1
assert_fail "whitespace-only stderr is success" $?
icat_error_message "$(printf '\n\n')" >/dev/null 2>&1
assert_fail "newlines-only stderr is success" $?

# kitty colorizes the filename in its errors; the codes must not reach the user.
coloured=$(printf 'Failed to process \033[31mlogo.svg\033[39m: bad format')
assert_eq "ansi codes stripped" "Failed to process logo.svg: bad format" \
  "$(icat_error_message "$coloured")"

# Multi-line stderr collapses to one line so it fits a single error message.
multi=$(printf 'first problem\nsecond problem')
assert_eq "multi-line collapsed" "first problem second problem" "$(icat_error_message "$multi")"

# --- parse_stty_size --------------------------------------------------------
# Regression: the script used `cols=$(tput cols)`, but tput reads the window
# size via an ioctl on stdout, which a command substitution has turned into a
# pipe. tput then silently returns the terminfo default 80x24, so every
# placement coordinate was computed for the wrong screen and the image landed
# in the upper-left instead of centered. stty reads the ioctl from stdin.

# stty prints "ROWS COLS"; the script wants "COLS ROWS".
assert_eq "stty size is reordered to cols rows" "170 49" "$(parse_stty_size '49 170')"
assert_eq "leading/trailing space tolerated"    "170 49" "$(parse_stty_size '  49 170  ')"
assert_eq "multiple spaces tolerated"           "80 24"  "$(parse_stty_size '24    80')"

parse_stty_size '' >/dev/null 2>&1;         assert_fail "empty stty output rejected" $?
parse_stty_size 'unknown' >/dev/null 2>&1;  assert_fail "non-numeric rejected" $?
parse_stty_size '49' >/dev/null 2>&1;       assert_fail "single number rejected" $?
parse_stty_size '0 170' >/dev/null 2>&1;    assert_fail "zero rows rejected" $?
parse_stty_size '49 0' >/dev/null 2>&1;     assert_fail "zero cols rejected" $?
parse_stty_size 'stty: stdin isnt a terminal' >/dev/null 2>&1
assert_fail "stty error message rejected" $?

# The concrete failure this caused, on the real 170x49 window: an 80x24 screen
# yields a small box parked high and left, instead of a centered one.
read -r bad_c bad_r bad_l bad_t <<<"$(compute_geometry 400 100 80 24 3060 1960)"
read -r good_c good_r good_l good_t <<<"$(compute_geometry 400 100 170 49 3060 1960)"
if (( good_c > bad_c && good_t > bad_t )); then ok; else
  bad "wrong terminal size misplaces the image" "80x24 gave ${bad_c}x${bad_r}@${bad_l}x${bad_t}, 170x49 gave ${good_c}x${good_r}@${good_l}x${good_t}"
fi
# With the real size, the image must be vertically centered within a row.
centre_off=$(( (49 - good_r) / 2 - good_t ))
assert_eq "real size centers vertically" "0" "$centre_off"

# --- overlay state file -----------------------------------------------------
# Replacing one image with another closes the old overlay *after* the new
# overlay's id has been recorded, so the old overlay's exit trap must not
# delete a state file that now belongs to its replacement.

export TMPDIR="$FIXTURE_DIR"
SF=$(state_file)

printf '77\n' >"$SF"
KITTY_WINDOW_ID=77 clear_own_state
[[ -f $SF ]] && bad "overlay clears its own id" "state file still present" || ok

printf '88\n' >"$SF"
KITTY_WINDOW_ID=77 clear_own_state
[[ -f $SF ]] && ok || bad "overlay leaves a newer id alone" "state file was deleted"
assert_eq "newer id survives cleanup" "88" "$(cat "$SF")"

rm -f "$SF"
KITTY_WINDOW_ID=77 clear_own_state
assert_ok "cleanup with no state file is not an error" $?

printf '99\n' >"$SF"
( unset KITTY_WINDOW_ID; clear_own_state )
[[ -f $SF ]] && ok || bad "cleanup without a window id is a no-op" "state file was deleted"
rm -f "$SF"

# --- reporting --------------------------------------------------------------

printf '\n'
if (( FAIL == 0 )); then
  printf 'ok - %d tests passed\n' "$PASS"
  exit 0
fi
printf 'FAILED - %d passed, %d failed\n' "$PASS" "$FAIL"
for n in "${FAILED_NAMES[@]}"; do printf '  - %s\n' "$n"; done
exit 1
