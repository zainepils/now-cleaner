#!/bin/sh
# Package the clean, committed source as a drag-to-Applications disk image.
set -eu
cd "$(dirname "$0")/.."
sh scripts/package_release.sh
short=$(git rev-parse --short HEAD)
if [ "$(uname -m)" != arm64 ]; then
    echo 'This release recipe is for Apple silicon only.' >&2
    exit 1
fi
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
ditto --noextattr --noqtn 'dist/NOW Cleaner.app' "$stage/NOW Cleaner.app"
ln -s /Applications "$stage/Applications"
mkdir "$stage/Details"
cp LICENSE NOTICE docs/install.md docs/privacy.md "$stage/Details/"
cp "dist/release-$short/BUILD_INFO.txt" "dist/release-$short/DEPENDENCIES.txt" "$stage/Details/"
cat > "$stage/Read Me.txt" <<'EOF'
INSTALL NOW CLEANER

1. Drag NOW Cleaner into the Applications shortcut beside it.
2. Eject this installer.
3. Open NOW Cleaner from Applications.

Apple-silicon Macs only (M-series). Python is already included.
This personal-use preview is NOT Apple-notarized.

If macOS cannot verify the developer, read the installation guide:
https://github.com/zainepils/now-cleaner/blob/main/docs/install.md
Only use Privacy & Security > Open Anyway if you trust this download.
Do not disable your security settings or override malware/damage warnings.

Start with local files; Google Drive connection is optional and needs setup.
Word/PowerPoint visual packs need LibreOffice installed separately.

Source, privacy and help: https://github.com/zainepils/now-cleaner
Licenses, source commit and dependency details are in the Details folder.
EOF
hdiutil create -ov -volname 'NOW Cleaner - Drag to Applications' -srcfolder "$stage" \
    -format UDZO -imagekey zlib-level=9 dist/NOW-Cleaner-Apple-Silicon.dmg
hdiutil verify dist/NOW-Cleaner-Apple-Silicon.dmg
cp "dist/release-$short/BUILD_INFO.txt" dist/BUILD_INFO.txt
cp "dist/release-$short/DEPENDENCIES.txt" dist/DEPENDENCIES.txt
(cd dist && shasum -a 256 NOW-Cleaner-Apple-Silicon.dmg > SHA256SUMS.txt)
echo 'Installer prepared and verified. Nothing uploaded.'
