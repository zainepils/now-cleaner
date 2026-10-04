#!/bin/sh
# Package the clean, committed source as a drag-to-Applications disk image.
set -eu
cd "$(dirname "$0")/.."
sh scripts/package_release.sh
short=$(git rev-parse --short HEAD)
case "$(uname -m)" in
    arm64) filename=NOW-Cleaner-Apple-Silicon.dmg; platform_label='Apple-silicon Macs (M-series)' ;;
    x86_64) filename=NOW-Cleaner-Intel-Mac.dmg; platform_label='Intel-based Macs' ;;
    *) echo 'Unsupported Mac architecture.' >&2; exit 1 ;;
esac
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

Python is already included. See the architecture note below.
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
printf '\nThis installer is for %s only.\n' "$platform_label" >> "$stage/Read Me.txt"
hdiutil create -ov -volname 'NOW Cleaner - Drag to Applications' -srcfolder "$stage" \
    -format UDZO -imagekey zlib-level=9 "dist/$filename"
hdiutil verify "dist/$filename"
cp "dist/release-$short/BUILD_INFO.txt" dist/BUILD_INFO.txt
cp "dist/release-$short/DEPENDENCIES.txt" dist/DEPENDENCIES.txt
(cd dist && shasum -a 256 "$filename" > SHA256SUMS.txt)
echo 'Installer prepared and verified. Nothing uploaded.'
