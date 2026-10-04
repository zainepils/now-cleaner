# Privacy and Data Flow

This describes the current source implementation, not a guarantee about every dependency,
future release, operating-system service, or third-party provider. NOW Cleaner has no
developer-operated backend, analytics, telemetry, advertising, or automatic crash-report
upload in its application code. It does not send course material to the project maintainer.

## What Leaves Your Computer?

| Action | Recipient | Information sent |
| --- | --- | --- |
| Local module import, preview, preparation and save | None from application code | Processing stays on your computer. |
| One-off cleaning without a configured OpenAI key | None from application code | Processing stays on your computer. |
| One-off filename naming with a configured OpenAI key | OpenAI Responses API | ZIP filename stem, naming instructions, model parameters and your API key for authentication. Document contents are not included. |
| Connect or reconnect Google Drive | Google OAuth | OAuth client information, requested permission, consent and token exchange. Your browser opens Google's sign-in page. |
| Drive setup tests | Google Drive and Docs | Synthetic test documents/PDFs and their metadata. These use no course content. |
| Send to Google Drive / retry | Google Drive and Docs | Generated course packs, group/module names, ownership identifiers and file metadata. Course contents are included in these uploads. |
| Open NotebookLM or Google Cloud Console | Google, through your browser | The destination URL and normal browser traffic. NOW Cleaner does not automate NotebookLM. |
| Open a newly generated HTML summary | None automatically from report assets | Fonts and styling are local; no remote font, script or image assets. Clicking a listed external resource can open its website. |

Google and OpenAI receive normal connection information, such as IP addresses, and apply
their own policies. Connecting Drive does not itself upload course content, but it
exchanges credentials with Google. Installing dependencies or fetching this repository
also contacts package registries/GitHub; those are not runtime telemetry.

**Important:** The legacy one-off cleaner discovers an OpenAI key from
`OPENAI_API_KEY` or `~/.config/now-cleaner/openai_api_key` and may use it for filename
naming without a separate consent prompt. Leave both unconfigured for local-only
one-off processing. Module naming never uses OpenAI. Cached names can avoid a request.
No app update-checking or background course monitoring is implemented.
Older HTML reports may still contain Google Fonts references; regenerate them with
this version to remove those remote assets. Existing output folders are not rewritten.

## What Stays Locally?

In the local-only Windows preview, module inventory/previews use
`%LOCALAPPDATA%\NOW Cleaner` instead of macOS Application Support. Google Drive is
disabled; no Google tokens are stored by that preview. Local Windows files use existing
user-folder permissions, not POSIX permission settings or custom app-configured ACLs.

- `~/Library/Application Support/NOW Cleaner/inventory.sqlite3`: module names,
  destination paths, NotebookLM links, hashes, original filenames, pack membership,
  revision history, preferences, Drive IDs/upload receipts, connected account email
  and identifier, and the path to the selected OAuth client file.
- The same Application Support directory: staged exports, original content and
  prepared previews, plus per-module lock files. Previews are not automatically pruned.
- The module destination (by default under `~/Documents/NOW Cleaner`): originals,
  current upload packs, latest changes, reports and recoverable previous revisions.
- One-off outputs: cleaned files and reports containing paths, filenames, counts and
  conversion/link information. Replaced outputs have retained local backups.
- `~/.config/now-cleaner/zip_name_cache.json`: raw ZIP names and cleaned labels for
  the one-off workflow. Reports include only the current run's naming entries.
- macOS Keychain: Google access/refresh credentials. Drive refuses plaintext-token
  fallback. An optional OpenAI key file is separate and **is plaintext**, not Keychain-managed.
- UI/terminal progress messages: local diagnostics, which can include file/group names.
  They are not automatically submitted to the maintainer.

Local file permissions restrict the inventory, but course files and the inventory are
not encrypted by NOW Cleaner. macOS backups, iCloud Drive or another sync service can
copy folders independently of the app. Choose a non-synced destination if that matters.

## Google Permission and Disconnect

The app requests `drive.file`, rather than access to the entire Drive. This applies to
files the app creates or files explicitly made available to it. The desktop OAuth flow
uses PKCE and a temporary loopback listener at `127.0.0.1`, only during sign-in.

Disconnect deletes local Google tokens and resets saved sync verification. It does
not delete your Drive files, local course history or all account metadata, and does
not revoke Google's server-side grant. To revoke access, use your Google account's
third-party connections settings. To delete uploaded packs, remove them from Drive
yourself and review any corresponding NotebookLM sources.

## Removing Local Data

Quit the app before manual cleanup. Removing the Application Support folder deletes
module tracking, preferences and staged content, not module destinations or Drive files.
Delete unwanted module destinations, one-off outputs/backups and naming caches separately.
Disconnect before deleting state if you also want local Google tokens removed. Remove
any OpenAI key file/environment setting separately. There is no automatic retention timer.

Do not post reports, inventories, ZIPs, screenshots of real course content, OAuth files,
keys or logs publicly. Use fictional demo content when reporting problems.

## How To Check These Statements

- `now_cleaner/drive.py`: OAuth, Keychain, Google API calls and upload logic.
- `now_cleaner/store.py`: inventory and local settings.
- `now_cleaner/engine.py` and `now_cleaner/packs.py`: local processing and staging.
- `clean_now_notebooklm.py`: optional OpenAI request, naming cache and self-contained reports.
- `now_cleaner/module_ui.py`: user-triggered operations and browser/folder links.
- `tests/test_privacy.py`: synthetic local workflows with Python network connections
  blocked, and an HTML asset check. These are regression checks, not a whole-system
  network audit or proof about LibreOffice/browser behaviour.

You can build from source, inspect changes and test local-only operation offline.
App bundles are currently ad-hoc signed, not Apple-notarized. Public source availability
does not prove that an arbitrary downloaded binary matches it. Check the release source
commit and checksum when provided; checksums identify bytes, not safety.
Windows installers are currently unsigned. See [Windows preview guidance](windows.md).
