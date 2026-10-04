# Install NOW Cleaner

## Download for Mac

[Download for Apple-silicon Macs](https://github.com/zainepils/now-cleaner/releases/download/v0.3.1/NOW-Cleaner-Apple-Silicon.dmg)

[Download for Intel Macs](https://github.com/zainepils/now-cleaner/releases/download/v0.3.1/NOW-Cleaner-Intel-Mac.dmg)

There are separate personal-use previews for **Apple-silicon Macs (M-series)** and
**Intel Macs (x86_64)**. Python is included: no coding or terminal setup is needed.
The app targets macOS 11 or later. Intel builds are tested on a macOS 15 GitHub runner;
Apple-silicon builds are checked on macOS 14 and packaged workflows tested on macOS 27.
Not every older macOS release or physical Intel Mac has been verified.

To check your Mac, choose Apple menu > About This Mac. Look for a **Chip** beginning
with Apple M for the Apple-silicon download, or **Processor: Intel** for the Intel download.

## Install

1. Download and open the `.dmg` file above.
2. Drag **NOW Cleaner** into the **Applications** shortcut in the installer window.
3. Eject the installer, then open NOW Cleaner from Applications or Spotlight.

If replacing an existing installation, quit NOW Cleaner first. Replacing the app does
not remove your saved modules or course folders. Keep a backup before upgrading.

## First-Launch Security Warning

**This release is ad-hoc signed, not Apple Developer ID-signed or notarized.** macOS
may say it cannot verify the developer or check the app for malicious software.
This is a real limitation, not evidence that the app has been approved by Apple.

Only if you trust this repository and the download:

1. Try opening the app once, then dismiss the warning.
2. Open **System Settings > Privacy & Security**.
3. If macOS offers **Open Anyway** for NOW Cleaner, choose it and confirm.

On older macOS releases the settings app may be called System Preferences.
See [Apple's official guide](https://support.apple.com/en-ie/102445).
Do not disable Gatekeeper, run quarantine-removal commands, or override a warning
that the app contains malware or is damaged. Report unexpected warnings instead.
Managed work/school Macs may prohibit exceptions.

## Start With Local Files

1. Choose **Create your first module** and enter its name.
2. Choose **Add download**, then ZIP files or a folder containing ZIPs.
3. Check changes, prepare upload files, then save the update.
4. Open the files to upload and follow the included NotebookLM checklist.

You do not need a Google Cloud project, Google connection or OpenAI key for local module
processing. Drive sync is optional and still needs the technical
[personal-account setup and sync test](drive-setup.md).

## Word and PowerPoint Packs

Visual packs made from Office files require [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/),
installed separately in Applications. Choose the LibreOffice download matching your
Mac's processor: Apple silicon or Intel.
It is not needed merely to open NOW Cleaner or to process text/PDF packs.
The one-off cleaner can retain `.docx` and `.pptx` originals without this conversion.
NOW Cleaner will report a missing converter; it does not install LibreOffice for you.

## Privacy, Updates and Removal

See [Privacy and Data Flow](privacy.md) before enabling external services.
New HTML reports do not fetch remote assets. The one-off cleaner may contact OpenAI
if you already have a naming API key configured; local module naming does not.

Updates are manual: return to GitHub Releases for a newer build. There is no automatic
updater. To uninstall, quit and move the app out of Applications. Your saved files/history
remain; the privacy guide explains separate data cleanup and Google disconnect.

Release assets include a SHA-256 checksum, source commit and build/dependency details
for technical verification. A checksum is not proof of safety. The source uses the
PolyForm Noncommercial license; bundled third-party components retain their own terms.
