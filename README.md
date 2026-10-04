# NOW Cleaner

A local macOS desktop app for organising NTU NOW course ZIP exports and preparing NotebookLM sources. Save a module, review changes between exports, and maintain stable source packs instead of repeatedly rebuilding everything. Optional Google Drive integration updates linked packs in place; **live NotebookLM syncing must be manually verified for your account before real course uploads are enabled**.

The repository's code and documentation are available under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, modify, and share them for permitted noncommercial purposes, provided you pass on the license terms and [required notice](NOTICE). Commercial use requires separate permission from the owner. This is source-available software, not an open-source license. The license does not grant rights to any course content or other files a user processes with the tool.

## Modules & updates

1. Create a module with a required name and saved destination. Default: one NotebookLM notebook per module, 50 source slots, 15 reserved for independently added sources.
2. Select one or more ZIPs, or a folder containing ZIPs.
3. Preview new, changed, unchanged, conflicting and possible-renamed files. Review uncertain pack categories. Partial imports keep missing earlier files; full snapshots only remove files you explicitly approve.
4. Prepare stable lecture/seminar packs grouped into four-week ranges, plus assessment/reference packs. Review affected packs, warnings and estimated source count.
5. Apply the local update. Previous revisions remain recoverable through History.
6. Use local uploads, or Sync / Retry Drive after completing [Drive setup and the synthetic sync test](docs/drive-setup.md).

Contents are compared using SHA-256 and original course paths, not ZIP dates or changing archive names. Identical duplicate exports are deduplicated. Conflicting paths across ZIPs require a version choice. Saved filenames and pack membership remain stable between updates.

Text packs become Google Docs in Drive mode. Slides, Office documents, images and PDFs become visual PDF packs; Office conversion requires LibreOffice. Originals are kept locally, including `.pptx`, `.docx` and `.epub`. EPUB text packs omit layout/images with an explicit warning. Unsupported files are retained locally and reported, not silently substituted into incomplete packs. Some image formats require a Pillow decoder not present in every installation; conversion failure blocks the update rather than dropping the image. Animation/multiple image frames are not included in visual packs.

Pack generation caps source words, characters, pages and bytes and splits oversized groups into numbered parts. Splits are shown before publication. Estimated counts include reserved external sources and retired linked packs. The app cannot read NotebookLM's actual source count. If over budget, adjust category assignments or reservations; automatic consolidation is not implemented.

### Local layout

Each module has its own marked folder and immutable revision directories. Stable folder links point to the committed revision:

```text
Module folder/
  Current Files/       # original documents with stable flattened names
  Packs/               # complete current NotebookLM-ready packs
  Latest Update/       # actual copies of new/changed packs
  Reports/             # checklist and update metadata
  revisions/           # recoverable previous versions
```

The folder links are managed by the app; files inside Latest Update are real copies, not file shortcuts. Local-only uploads still require manually replacing changed NotebookLM sources. The checklist separates new, replacement and retired packs. History stores local revisions, not verified NotebookLM state.

## Drive integration

Sign-in uses a desktop OAuth client, PKCE, `drive.file` permission and macOS Keychain. A localhost listener exists only during sign-in; no hosted web UI or persistent server is used.

The app uploads private app-managed packs only after format-specific manual sync verification. Existing Drive file IDs are retained. Per-pack receipts support retries and prevent duplicate creation after interrupted requests. External edits, missing files, account mismatches and unsafe writes block replacement. Disconnect removes tokens without deleting course content.

**Drive upload success is not proof of NotebookLM sync.** The app reports "Drive updated; NotebookLM sync pending". New packs need importing from Drive once; retired sources need manual removal. See [setup/privacy guidance](docs/drive-setup.md).

No NTU monitoring, automatic course downloading, background scheduling, NotebookLM scraping or direct NotebookLM API integration is included.

## One-off cleaner

The original workflow remains on its own tab and CLI. It flattens course ZIPs, removes SVGs, preserves supported documents/EPUBs/images/audio, converts other formats to text where possible, and produces HTML and text reports. Supported images can be excluded. `.pptx` and `.docx` are copied without conversion; older `.ppt`/`.doc` text decoding may be unreadable.

Optional similarity merging is heuristic and bounded to 200 text candidates / 20 MB combined input. Review results before uploading. Previous overwritten output is retained in a hidden sibling backup rather than automatically deleted.

Without an OpenAI key, ZIP labels are cleaned locally. Optional `OPENAI_API_KEY` or `~/.config/now-cleaner/openai_api_key` naming sends only the ZIP filename stem, never its contents. Keys are no longer accepted as command-line values. Module naming does not use AI. Output reports include only the current run's naming entries.

Google's [supported sources](https://support.google.com/gemininotebook/answer/16215270?hl=en) can change independently of this app.

## Run from source

The desktop app requires macOS and Python 3.12+ with Tkinter. Install module/Drive dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python now_cleaner_desktop.py
```

The one-off CLI still uses only the Python standard library:

```sh
python3 clean_now_notebooklm.py --source /path/to/export-zips --merge-similar
# Optional: --exclude-images, --overwrite
```

Module CLI:

```sh
.venv/bin/python -m now_cleaner.cli create "Marketing Principles" --destination /path/to/modules
.venv/bin/python -m now_cleaner.cli list
.venv/bin/python -m now_cleaner.cli preview MODULE_ID /path/to/export.zip
.venv/bin/python -m now_cleaner.cli prepare PREVIEW_TOKEN --decisions /path/to/review-decisions.json
.venv/bin/python -m now_cleaner.cli apply PREVIEW_TOKEN --approve-warnings
.venv/bin/python -m now_cleaner.cli sync MODULE_ID
```

Use `--help` for connect, probe, confirm-probe, history and disconnect commands. `--state-dir` supports an isolated inventory for testing. Prepared preview tokens become stale after another committed update. Decision JSON maps preview item keys to `group`, zero-based `candidate`, `rename` (`keep`/`move`), `duplicate` (`keep`), `remove` or `skip`. Review warnings before using `--approve-warnings`.

## Build a local macOS app

```sh
.venv/bin/python -m pip install pyinstaller
.venv/bin/pyinstaller --noconfirm --clean --windowed --name 'NOW Cleaner' \
  --hidden-import keyring.backends.macOS --collect-data googleapiclient \
  --add-data 'docs/drive-setup.md:docs' now_cleaner_desktop.py
```

The result is `dist/NOW Cleaner.app`. Python and libraries are bundled; LibreOffice is an external dependency for visual Office packs. Local builds are ad-hoc signed, not notarized for public distribution. Public downloadable releases need a separate signing/distribution pass.

## Tests and data safety

```sh
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/make_demo.py /tmp/now-cleaner-demo
```

Tests use fictional content and mocked Google services; they do not prove live Google/NotebookLM compatibility. Local inventory lives under `~/Library/Application Support/NOW Cleaner`. OAuth configuration, tokens, real exports, outputs, caches and logs must never be committed. History and staged previews consume local disk and are not automatically pruned in this release.

ZIP processing rejects unsafe paths, symlinks, collisions and excessive member/expansion budgets. Nested document reads and one-off merging are bounded. This is not malware scanning or a complete sandbox for LibreOffice/PDF parsers: process trusted course exports only. Conversions are best-effort, do not OCR scanned PDFs and may not retain every Office feature.

## Project development

Zaine Pilsworth designed the workflow, defined the product requirements and user experience, and led testing and refinement of NOW Cleaner.

Codex was used as an AI coding assistant throughout implementation, debugging and packaging. Zaine reviewed outputs, tested behaviour, refined requirements and directed changes throughout development.

This project should be described as AI-assisted development rather than independently hand-coded end-to-end.
