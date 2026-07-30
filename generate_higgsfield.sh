#!/usr/bin/env bash
# Higgsfield Marketing Studio PoC:
#   1) upload face/reference image
#   2) create custom avatar
#   3) (optional) create product from same/other image
#   4) generate UGC marketing_studio_video
#
# Auth: official CLI uses browser OAuth (not FAL-style API key paste):
#   higgsfield auth login
#
# Usage:
#   ./generate_higgsfield.sh example.png
#   ./generate_higgsfield.sh example.png --product-image example.1.png
#   ./generate_higgsfield.sh example.png --name "UGC Creator" --mode ugc --duration 15

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ASSETS_DIR="$ROOT/reference_assets"
OUTPUT_DIR="$ROOT/output/higgsfield"
PROMPT_FILE="$ROOT/prompt_higgsfield.txt"
STATE_DIR="$ROOT/.higgsfield_state"

IMAGE_NAME=""
PRODUCT_IMAGE_NAME=""
AVATAR_NAME="ugc_poc"
MODE="ugc"
DURATION="15"
RESOLUTION="720p"
ASPECT_RATIO="9:16"
SKIP_AVATAR=0
EXISTING_AVATAR_ID=""
EXISTING_PRODUCT_ID=""

die() { echo "Error: $*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") <image> [options]

  <image>                 Filename inside reference_assets/ (avatar face)

Options:
  --product-image NAME    Product image in reference_assets/ (default: same as avatar)
  --name NAME             Avatar name (default: ugc_poc)
  --mode MODE             Marketing Studio mode (default: ugc)
  --duration N            Seconds (default: 15)
  --resolution RES        e.g. 720p (default: 720p)
  --aspect-ratio R        e.g. 9:16 (default: 9:16)
  --avatar-id ID          Reuse an existing Marketing Studio avatar id
  --product-id ID         Reuse an existing Marketing Studio product id
  --prompt-file PATH      Prompt file (default: prompt_higgsfield.txt)
  -h, --help              Show help
EOF
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing '$1'. Install: npm i -g @higgsfield/cli"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --product-image) PRODUCT_IMAGE_NAME="${2:-}"; shift 2 ;;
    --name) AVATAR_NAME="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --duration) DURATION="${2:-}"; shift 2 ;;
    --resolution) RESOLUTION="${2:-}"; shift 2 ;;
    --aspect-ratio) ASPECT_RATIO="${2:-}"; shift 2 ;;
    --avatar-id) EXISTING_AVATAR_ID="${2:-}"; shift 2 ;;
    --product-id) EXISTING_PRODUCT_ID="${2:-}"; shift 2 ;;
    --prompt-file) PROMPT_FILE="${2:-}"; shift 2 ;;
    -*) die "Unknown flag: $1" ;;
    *)
      if [[ -z "$IMAGE_NAME" ]]; then IMAGE_NAME="$1"; shift
      else die "Unexpected arg: $1"; fi
      ;;
  esac
done

[[ -n "$IMAGE_NAME" ]] || { usage; die "image filename is required"; }
PRODUCT_IMAGE_NAME="${PRODUCT_IMAGE_NAME:-$IMAGE_NAME}"

need_cmd higgsfield
need_cmd jq
need_cmd curl

# Headless auth: inject credentials / refresh / Playwright email+password
AUTH_PY="$ROOT/ensure_higgsfield_auth.py"
if [[ -f "$AUTH_PY" ]]; then
  echo "==> Ensuring Higgsfield auth (headless)..."
  if [[ -f "$ROOT/.venv/bin/python" ]]; then
    "$ROOT/.venv/bin/python" "$AUTH_PY"
  else
    python3 "$AUTH_PY"
  fi
elif ! higgsfield account status --json >/dev/null 2>&1; then
  die "Not authenticated and ensure_higgsfield_auth.py missing.
Run:  higgsfield auth login
Or add ensure_higgsfield_auth.py + HIGGSFIELD_EMAIL/PASSWORD in .env"
fi

if ! higgsfield account status --json >/dev/null 2>&1; then
  die "Higgsfield auth failed after ensure step."
fi

AVATAR_PATH="$ASSETS_DIR/$IMAGE_NAME"
PRODUCT_PATH="$ASSETS_DIR/$PRODUCT_IMAGE_NAME"
[[ -f "$AVATAR_PATH" ]] || die "Missing avatar image: $AVATAR_PATH"
[[ -f "$PRODUCT_PATH" ]] || die "Missing product image: $PRODUCT_PATH"
[[ -f "$PROMPT_FILE" ]] || die "Missing prompt file: $PROMPT_FILE"

PROMPT="$(<"$PROMPT_FILE")"
mkdir -p "$OUTPUT_DIR" "$STATE_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$OUTPUT_DIR/${AVATAR_NAME}_${STAMP}"
mkdir -p "$RUN_DIR"

echo "==> Auth OK"
echo "==> Avatar image:  reference_assets/$IMAGE_NAME"
echo "==> Product image: reference_assets/$PRODUCT_IMAGE_NAME"
echo "==> Mode: $MODE | ${DURATION}s | $ASPECT_RATIO | $RESOLUTION"

upload_file() {
  local path="$1"
  local out
  out="$(higgsfield upload create "$path" --json)"
  echo "$out" >"$RUN_DIR/upload_$(basename "$path").json"
  local id url
  id="$(echo "$out" | jq -r 'if type=="array" then .[0] else . end | .id // .upload_id // .data.id // empty')"
  url="$(echo "$out" | jq -r 'if type=="array" then .[0] else . end | .url // .cloudfront_url // .data.url // empty')"
  [[ -n "$id" ]] || die "Upload failed for $path (no id). Raw: $out"
  [[ -n "$url" ]] || die "Upload failed for $path (no url). Raw: $out"
  printf '%s\t%s\n' "$id" "$url"
}

# CLI sometimes returns an object, sometimes an array (full list after create).
json_id() {
  local json="$1"
  local preferred_name="${2:-}"
  echo "$json" | jq -r --arg name "$preferred_name" '
    (if type=="array" then
       (if $name != "" then (.[] | select(.name==$name)) else .[0] end)
     else . end)
    | .id // .avatar_id // .product_id // .data.id // empty
  ' | head -n 1
}

AVATAR_ID="$EXISTING_AVATAR_ID"
PRODUCT_ID="$EXISTING_PRODUCT_ID"

if [[ -z "$AVATAR_ID" ]]; then
  echo "==> Uploading avatar image..."
  IFS=$'\t' read -r AVATAR_UPLOAD_ID AVATAR_UPLOAD_URL < <(upload_file "$AVATAR_PATH")
  echo "    upload id:  $AVATAR_UPLOAD_ID"
  echo "    upload url: $AVATAR_UPLOAD_URL"

  echo "==> Creating Marketing Studio avatar '$AVATAR_NAME'..."
  AVATAR_JSON="$(higgsfield marketing-studio avatars create \
    --name "$AVATAR_NAME" \
    --image "$AVATAR_UPLOAD_ID" \
    --json)"
  echo "$AVATAR_JSON" >"$RUN_DIR/avatar.json"
  AVATAR_ID="$(json_id "$AVATAR_JSON" "$AVATAR_NAME")"
  [[ -n "$AVATAR_ID" && "$AVATAR_ID" != "null" ]] || die "Avatar create failed. Raw: $AVATAR_JSON"
  echo "    avatar id: $AVATAR_ID"
else
  echo "==> Reusing avatar id: $AVATAR_ID"
fi

if [[ -z "$PRODUCT_ID" ]]; then
  echo "==> Uploading product image..."
  IFS=$'\t' read -r PRODUCT_UPLOAD_ID _PRODUCT_UPLOAD_URL < <(upload_file "$PRODUCT_PATH")
  echo "    upload id: $PRODUCT_UPLOAD_ID"

  echo "==> Creating Marketing Studio product..."
  PRODUCT_JSON="$(higgsfield marketing-studio products create \
    --title "Seamless Wireless Top" \
    --description "Soft seamless everyday support top for UGC ecommerce ads" \
    --image "$PRODUCT_UPLOAD_ID" \
    --json)"
  echo "$PRODUCT_JSON" >"$RUN_DIR/product.json"
  PRODUCT_ID="$(json_id "$PRODUCT_JSON")"
  [[ -n "$PRODUCT_ID" && "$PRODUCT_ID" != "null" ]] || die "Product create failed. Raw: $PRODUCT_JSON"
  echo "    product id: $PRODUCT_ID"
else
  echo "==> Reusing product id: $PRODUCT_ID"
fi

printf '[{"id":"%s","type":"custom"}]\n' "$AVATAR_ID" >"$RUN_DIR/avatars.json"
printf '["%s"]\n' "$PRODUCT_ID" >"$RUN_DIR/product_ids.json"
printf '%s\n' "$PROMPT" >"$RUN_DIR/prompt.txt"

echo "==> Generating marketing_studio_video (this can take several minutes)..."
GEN_JSON="$(higgsfield generate create marketing_studio_video \
  --prompt "$PROMPT" \
  --avatars @"$RUN_DIR/avatars.json" \
  --product_ids @"$RUN_DIR/product_ids.json" \
  --mode "$MODE" \
  --duration "$DURATION" \
  --resolution "$RESOLUTION" \
  --aspect_ratio "$ASPECT_RATIO" \
  --wait \
  --wait-timeout 30m \
  --json)" || die "Video generation failed"

echo "$GEN_JSON" >"$RUN_DIR/generate.json"

VIDEO_URL="$(echo "$GEN_JSON" | jq -r '
  .. | objects
  | .result_url // .video_url // .url // empty
' | head -n 1)"

if [[ -z "$VIDEO_URL" || "$VIDEO_URL" == "null" ]]; then
  # common CLI shape: array of jobs with results
  VIDEO_URL="$(echo "$GEN_JSON" | jq -r '
    (.[].results[]?.url? // .[].result_url? // empty)
  ' 2>/dev/null | head -n 1 || true)"
fi

[[ -n "$VIDEO_URL" && "$VIDEO_URL" != "null" ]] || {
  echo "Generation finished but no video URL parsed. See $RUN_DIR/generate.json" >&2
  exit 1
}

OUT_MP4="$RUN_DIR/ugc_${MODE}.mp4"
echo "==> Downloading $VIDEO_URL"
curl -fsSL "$VIDEO_URL" -o "$OUT_MP4"

cat >"$RUN_DIR/summary.json" <<EOF
{
  "avatar_id": "$AVATAR_ID",
  "product_id": "$PRODUCT_ID",
  "mode": "$MODE",
  "duration": "$DURATION",
  "aspect_ratio": "$ASPECT_RATIO",
  "resolution": "$RESOLUTION",
  "video_url": "$VIDEO_URL",
  "local_video": "$(basename "$OUT_MP4")"
}
EOF

echo "$AVATAR_ID" >"$STATE_DIR/last_avatar_id"
echo "$PRODUCT_ID" >"$STATE_DIR/last_product_id"

echo
echo "Done."
echo "  Avatar:  $AVATAR_ID"
echo "  Product: $PRODUCT_ID"
echo "  Video:   $OUT_MP4"
echo
echo "Reuse later:"
echo "  ./generate_higgsfield.sh $IMAGE_NAME --avatar-id $AVATAR_ID --product-id $PRODUCT_ID"
