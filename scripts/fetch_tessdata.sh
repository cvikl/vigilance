#!/usr/bin/env bash
# Fetch eng.traineddata (tessdata_fast) into data/tessdata/ and verify its sha256.
# tesserocr's wheel bundles libtesseract but no language data; this is the only file S4 needs.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:-data/tessdata}"
URL="https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata"
SHA="7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
mkdir -p "$DIR"
if [[ -f "$DIR/eng.traineddata" ]] && echo "$SHA  $DIR/eng.traineddata" | sha256sum -c --quiet; then
  echo "tessdata ok: $DIR/eng.traineddata"; exit 0
fi
curl -sSL -o "$DIR/eng.traineddata.tmp" "$URL"
echo "$SHA  $DIR/eng.traineddata.tmp" | sha256sum -c --quiet
mv "$DIR/eng.traineddata.tmp" "$DIR/eng.traineddata"
echo "tessdata fetched: $DIR/eng.traineddata"
