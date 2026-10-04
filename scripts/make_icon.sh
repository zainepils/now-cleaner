#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p assets
swift scripts/make_icon.swift assets/now-cleaner.png
iconset=$(mktemp -d)/NOWCleaner.iconset
mkdir -p "$iconset"
trap 'rm -rf "$(dirname "$iconset")"' EXIT
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" assets/now-cleaner.png --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" assets/now-cleaner.png --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o assets/now-cleaner.icns
