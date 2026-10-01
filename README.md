# NOW Cleaner

A local macOS desktop tool that turns exported course ZIPs into a flatter, easier-to-review collection of files for NotebookLM. It provides a Tkinter interface for a Python processing pipeline; no web server or port is involved.

The repository's code and documentation are available under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, modify, and share them for permitted noncommercial purposes, provided you pass on the license terms and [required notice](NOTICE). Commercial use requires separate permission from the owner. This is source-available software, not an open-source license. The license does not grant rights to any course content or other files a user processes with the tool.

## What it does

Choose a folder of ZIP exports, then run the cleaner. It extracts each archive, flattens nested folders into descriptive filenames, removes images, copies supported files, and converts some document and text formats to `.txt`. PowerPoint `.pptx` files are copied unchanged apart from their filenames, because NotebookLM now supports them directly; LibreOffice is not required. Files over the 200 MB limit are skipped and reported. Older `.ppt` files still receive only a best-effort text decode, which may produce unreadable output. It creates per-ZIP conversion reports and an HTML run summary. Optional similar-file merging concatenates related text sources and can remove the *generated* source copies after merging; the input ZIPs are not changed. Merging is heuristic, so review results before using them.

See Google's [supported source types](https://support.google.com/gemininotebook/answer/16215270?hl=en) for current NotebookLM compatibility.

Without an OpenAI key, ZIP labels are cleaned locally. If `OPENAI_API_KEY` or `~/.config/now-cleaner/openai_api_key` is set, the tool can request a short label from OpenAI and cache it locally. This optional request sends the ZIP's filename stem, not the ZIP contents. Do not use AI naming with sensitive filenames unless permitted.

The output is a sibling folder named `<source> - Cleaned and ready.` by default. An overwrite is allowed only for a folder marked as created by this version of NOW Cleaner. Processing happens in a temporary sibling folder first, so a failed run does not replace the previous output. Existing legacy outputs must be moved aside manually.

## Run from source

Requires macOS and Python 3 with Tkinter for the GUI. The processing CLI uses only the Python standard library.

```sh
python3 now_cleaner_desktop.py
# Or run the CLI:
python3 clean_now_notebooklm.py --source /path/to/export-zips --merge-similar
```

Run `python3 clean_now_notebooklm.py --help` for all options. Omit `--merge-similar` if you want separate output files. The UI has separate merge and overwrite controls; overwrite is off by default.

## Build a local macOS app

Use a Python installation with Tkinter. The build below makes an arm64 `.app` on an Apple Silicon Mac. The app contains Python and does not depend on the source checkout at runtime.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pyinstaller
.venv/bin/pyinstaller --noconfirm --clean --windowed --name 'NOW Cleaner' now_cleaner_desktop.py
```

The result is `dist/NOW Cleaner.app`. Local builds are ad-hoc signed by PyInstaller, not notarized for public distribution. A public downloadable release would need a signing/notarization and distribution pass.

## Tests and demo

```sh
python3 -m unittest discover -s tests -v
python3 scripts/make_demo.py /tmp/now-cleaner-demo
python3 clean_now_notebooklm.py --source /tmp/now-cleaner-demo --merge-similar
```

The demo generator creates fictional material only. Never commit real course exports, generated outputs, API keys, local caches, or run logs.

## Limitations

- No background scheduling or cloud sync. The user starts each run.
- Conversion is best-effort. Complex formatting, embedded media, and scanned PDFs are not OCR'd.
- Similar-file matching is heuristic; inspect merged files and reports before upload.
- No ZIP bomb protection or formal malware scanning. Use trusted exports only.
- The processor writes a local ZIP-name cache in `~/.config/now-cleaner`.
- The app is macOS-focused; the CLI may work elsewhere but is not validated there.

## Project development

Zaine Pilsworth designed the workflow, defined the product requirements and user experience, and led testing and refinement of NOW Cleaner.

Codex was used as an AI coding assistant throughout implementation, debugging and packaging. Zaine reviewed outputs, tested behaviour, refined requirements and directed changes throughout development.

This project should be described as AI-assisted development rather than independently hand-coded end-to-end.
