#!/bin/sh
# Build a traceable local archive, without uploading it or claiming notarization.
set -eu
cd "$(dirname "$0")/.."
if [ -n "$(git status --porcelain)" ]; then
    echo 'Commit source changes before packaging a release.' >&2
    exit 1
fi
python=.venv/bin/python
"$python" -m PyInstaller --noconfirm 'NOW Cleaner.spec'
codesign --verify --deep --strict 'dist/NOW Cleaner.app'
commit=$(git rev-parse HEAD)
short=$(git rev-parse --short HEAD)
folder="dist/release-$short"
mkdir -p "$folder"
ditto 'dist/NOW Cleaner.app' "$folder/NOW Cleaner.app"
{
    echo "Source: https://github.com/zainepils/now-cleaner/tree/$commit"
    echo "Commit: $commit"
    echo "Built UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Signing: ad-hoc; NOT Apple-notarized"
    "$python" --version
    echo "macOS: $(sw_vers -productVersion); architecture: $(uname -m)"
} > "$folder/BUILD_INFO.txt"
"$python" -m pip list --format=freeze > "$folder/DEPENDENCIES.txt"
ditto -c -k --keepParent "$folder" "dist/NOW-Cleaner-$short.zip"
(cd dist && shasum -a 256 "NOW-Cleaner-$short.zip" > "NOW-Cleaner-$short.sha256")
echo "Created dist/NOW-Cleaner-$short.zip and its SHA-256 checksum. Nothing uploaded."
