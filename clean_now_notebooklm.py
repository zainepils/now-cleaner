#!/usr/bin/env python3
"""Clean NOW zip exports for NotebookLM.

What this script does:
1) Reads zip files from ~/Downloads/NOW (default).
2) Creates an output folder next to source named:
   "<source folder name> - Cleaned and ready." (default).
3) Extracts each zip to a temp folder.
4) Flattens all files into one output folder (no nested subfolders kept).
5) Renames each file as:
   "<cleaned zip name> - <folder1> - <folder2> - ... - <original filename>".
   - If file is at zip root, uses "TOP LEVEL" as folder marker.
6) Converts unsupported formats to NotebookLM-friendly text where possible.
   - HTML/HTM -> TXT (clean text)
   - PPTX -> PDF (via LibreOffice/OpenOffice if available; else TXT fallback)
   - DOCX/PPTX/XLSX/EPUB -> TXT (best-effort text extraction)
   - CSV/TSV/JSON/XML/YAML/RTF/log-like text files -> TXT
7) Removes image files from output.
8) Optionally uses OpenAI once per zip to simplify the zip-name prefix (cached).
9) Writes per-zip conversion reports into SUMMARY/.
10) Creates SUMMARY/SUMMARY.html with navigable run results and zip labels.
11) Optional: merges similar text files into fewer sources for NotebookLM limits.
    - Enabled with --merge-similar
    - Can remove originals unless --keep-merged-sources is set.

Original zip files are never modified.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4
from collections import defaultdict
from datetime import datetime
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
import xml.etree.ElementTree as ET

# Broad supported set used for local NotebookLM workflows.
SUPPORTED_NOTEBOOKLM_EXTS = {
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".docx",
    ".csv",
    ".3g2",
    ".3gp",
    ".aac",
    ".aif",
    ".aifc",
    ".aiff",
    ".amr",
    ".au",
    ".avi",
    ".cda",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".opus",
    ".ra",
    ".ram",
    ".snd",
    ".wav",
    ".weba",
    ".wma",
    ".m4a",
}

NOTEBOOKLM_MAX_FILE_BYTES = 200_000_000

TEXT_LIKE_EXTS = {
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
    ".rtf",
    ".log",
    ".ini",
    ".cfg",
}

IGNORE_FILENAMES = {".ds_store"}
IGNORE_DIRNAMES = {"__macosx"}
IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
    ".svg",
    ".ico",
    ".avif",
}

MERGEABLE_EXTS = {
    ".txt",
    ".md",
    ".markdown",
}

ZIP_NAME_PROMPT = (
    "You rewrite course export zip names into short, clean labels for filenames. "
    "Return only the cleaned label, plain text, no quotes, no extra words. "
    "Rules: keep key module/topic words; remove dates/times, duplicate counters like '(1)', "
    "IDs, and noise; max 40 characters; use title case; letters/numbers/spaces only."
)
DEFAULT_KEY_FILE = Path("~/.config/now-cleaner/openai_api_key").expanduser()
OUTPUT_MARKER = ".now-cleaner-output.json"
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
PPT_HINT_RE = re.compile(r"(powerpoint|slides?)", re.IGNORECASE)
VIDEO_HINT_RE = re.compile(
    r"(youtube\.com|youtu\.be|vimeo\.com|panopto|kaltura|mediasite|wistia|brightcove|loom|video)",
    re.IGNORECASE,
)


@dataclass
class FileResult:
    source: Path
    output: Optional[Path]
    action: str
    note: str = ""


@dataclass
class LinkDetection:
    source: Path
    kind: str
    url: str
    snippet_before: str


@dataclass
class ZipRunSummary:
    zip_name: str
    zip_label: str
    label_source: str
    copied: int
    converted: int
    deleted: int
    skipped: int
    skipped_items: list[str]
    detections: list[LinkDetection]


@dataclass
class MergeGroupSummary:
    pattern: str
    merged_file: Path
    source_files: list[Path]
    avg_similarity: float
    removed_sources: int
    strategy: str = "similarity"


class HTMLToTextParser(HTMLParser):
    """Simple HTML to plain text parser with block-aware newlines."""

    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "tr",
        "td",
        "th",
        "br",
    }

    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and t in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        t = tag.lower()
        if t in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth == 0 and t in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._skip_depth == 0:
            self.parts.append(data)

    def get_text(self) -> str:
        raw = html.unescape("".join(self.parts))
        raw = raw.replace("\xa0", " ")
        raw = re.sub(r"\r\n?", "\n", raw)
        # Trim each line, collapse excessive blank lines
        lines = [line.strip() for line in raw.split("\n")]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract and clean NOW zip exports for NotebookLM")
    parser.add_argument(
        "source_folder",
        nargs="?",
        type=Path,
        help="Folder containing NOW zip files (positional alternative to --source)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("~/Downloads/NOW").expanduser(),
        help="Folder containing NOW zip files (default: ~/Downloads/NOW)",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="Name of output folder created next to source folder (default: '<source folder name> - Cleaned and ready.')",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace a previous NOW Cleaner output after a successful rebuild",
    )
    parser.add_argument(
        "--openai-api-key",
        default="",
        help="OpenAI API key (default: OPENAI_API_KEY env var, then ~/.config/now-cleaner/openai_api_key)",
    )
    parser.add_argument(
        "--openai-model",
        default="gpt-4.1-mini",
        help="OpenAI model used to clean zip names",
    )
    parser.add_argument(
        "--merge-similar",
        action="store_true",
        help="Merge similar text files after conversion to reduce source count",
    )
    parser.add_argument(
        "--merge-threshold",
        type=float,
        default=0.18,
        help="Jaccard token similarity threshold for merge candidates (0-1, default: 0.18)",
    )
    parser.add_argument(
        "--merge-min-group",
        type=int,
        default=2,
        help="Minimum number of similar files required to create a merged file (default: 2)",
    )
    parser.add_argument(
        "--keep-merged-sources",
        action="store_true",
        help="Keep original files after creating merged files",
    )
    return parser.parse_args()


def resolve_output_root(source_dir: Path, output_name: str) -> Path:
    name = output_name.strip() or f"{source_dir.name} - Cleaned and ready."
    if name in {".", ".."} or "/" in name or "\\" in name or Path(name).is_absolute():
        raise ValueError("Output name must be a single folder name, not a path.")
    output_root = source_dir.parent / name
    if output_root.is_symlink() or output_root.resolve() == source_dir:
        raise ValueError("Output must be a separate, non-symlink folder next to the source.")
    if output_root.resolve().parent != source_dir.parent:
        raise ValueError("Output must stay next to the source folder.")
    return output_root


def is_managed_output(output_root: Path, source_dir: Path) -> bool:
    if not output_root.is_dir() or output_root.is_symlink():
        return False
    try:
        marker = json.loads((output_root / OUTPUT_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return marker == {"application": "now-cleaner", "source": str(source_dir)}


def mark_output(output_root: Path, source_dir: Path) -> None:
    marker = {"application": "now-cleaner", "source": str(source_dir)}
    (output_root / OUTPUT_MARKER).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def load_api_key(cli_value: str) -> str:
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env_value = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_value:
        return env_value
    try:
        if DEFAULT_KEY_FILE.exists():
            return DEFAULT_KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return ""


def sanitize_name(name: str) -> str:
    # Keep readable names but strip filesystem-problem chars.
    clean = name.replace("/", "-").replace("\\", "-").replace(":", " -")
    clean = re.sub(r"[\x00-\x1f]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or "untitled"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def is_within_notebooklm_size_limit(path: Path) -> bool:
    try:
        return path.stat().st_size <= NOTEBOOKLM_MAX_FILE_BYTES
    except Exception:
        return False


def read_text_file(path: Path) -> str:
    encodings = ["utf-8", "utf-16", "utf-8-sig", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    # Last resort.
    return path.read_text(encoding="utf-8", errors="ignore")


def find_soffice() -> Optional[str]:
    candidates = [
        shutil.which("soffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/Applications/OpenOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def convert_pptx_to_pdf(src: Path) -> Optional[Path]:
    soffice = find_soffice()
    if not soffice:
        return None
    out_dir = src.parent
    cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception:
        return None
    pdf_path = out_dir / f"{src.stem}.pdf"
    return pdf_path if pdf_path.exists() else None


def convert_html_to_text(path: Path) -> str:
    parser = HTMLToTextParser()
    parser.feed(read_text_file(path))
    parser.close()
    return parser.get_text()


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml_names = sorted(
            n
            for n in zf.namelist()
            if n.startswith("word/")
            and n.endswith(".xml")
            and any(k in n for k in ("document", "header", "footer", "footnotes", "endnotes"))
        )
        chunks: list[str] = []
        for name in xml_names:
            data = zf.read(name)
            root = ET.fromstring(data)
            for el in root.iter():
                tag = el.tag
                if tag.endswith("}t") and el.text:
                    chunks.append(el.text)
                elif tag.endswith("}tab"):
                    chunks.append("\t")
                elif tag.endswith("}br") or tag.endswith("}cr"):
                    chunks.append("\n")
                elif tag.endswith("}p"):
                    chunks.append("\n")
        out = "".join(chunks)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def _natural_key_for_slide(name: str) -> tuple[int, str]:
    m = re.search(r"slide(\d+)\.xml$", name)
    if m:
        return (int(m.group(1)), name)
    return (10**9, name)


def extract_pptx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        slides = sorted(
            (n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
            key=_natural_key_for_slide,
        )
        lines: list[str] = []
        for i, slide in enumerate(slides, start=1):
            data = zf.read(slide)
            root = ET.fromstring(data)
            texts = [el.text for el in root.iter() if el.tag.endswith("}t") and el.text]
            if texts:
                lines.append(f"Slide {i}")
                lines.append("\n".join(texts))
                lines.append("")
        return "\n".join(lines).strip()


def extract_xlsx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if si.tag.endswith("}si"):
                    parts = [t.text or "" for t in si.iter() if t.tag.endswith("}t")]
                    shared_strings.append("".join(parts))

        sheet_names = sorted(
            (n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")),
            key=lambda x: int(re.search(r"sheet(\d+)\.xml$", x).group(1)) if re.search(r"sheet(\d+)\.xml$", x) else 10**9,
        )

        out_lines: list[str] = []
        for sheet in sheet_names:
            out_lines.append(f"[{Path(sheet).name}]")
            root = ET.fromstring(zf.read(sheet))
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                vals: list[str] = []
                for c in row:
                    if not c.tag.endswith("}c"):
                        continue
                    ctype = c.attrib.get("t", "")
                    val = ""
                    if ctype == "s":
                        v = next((x for x in c if x.tag.endswith("}v")), None)
                        if v is not None and v.text and v.text.isdigit():
                            idx = int(v.text)
                            if 0 <= idx < len(shared_strings):
                                val = shared_strings[idx]
                    elif ctype == "inlineStr":
                        texts = [x.text or "" for x in c.iter() if x.tag.endswith("}t")]
                        val = "".join(texts)
                    else:
                        v = next((x for x in c if x.tag.endswith("}v")), None)
                        if v is not None and v.text:
                            val = v.text
                    vals.append(val)
                if any(v.strip() for v in vals):
                    out_lines.append("\t".join(vals).rstrip())
            out_lines.append("")
        return "\n".join(out_lines).strip()


def strip_rtf_to_text(rtf_text: str) -> str:
    text = re.sub(r"\\par[d]?", "\n", rtf_text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_epub_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        html_files = sorted(
            n for n in zf.namelist() if n.lower().endswith((".html", ".htm", ".xhtml"))
        )
        chunks: list[str] = []
        for name in html_files:
            try:
                data = zf.read(name)
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                continue
            parser = HTMLToTextParser()
            parser.feed(text)
            parser.close()
            body = parser.get_text()
            if body:
                chunks.append(f"[{name}]\n{body}")
        return "\n\n".join(chunks).strip()


def convert_to_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".html", ".htm"}:
        return convert_html_to_text(path)
    if ext == ".docx":
        return extract_docx_text(path)
    if ext == ".pptx":
        return extract_pptx_text(path)
    if ext == ".xlsx":
        return extract_xlsx_text(path)
    if ext == ".epub":
        return extract_epub_text(path)
    if ext == ".rtf":
        return strip_rtf_to_text(read_text_file(path))
    if ext == ".json":
        try:
            obj = json.loads(read_text_file(path))
            return json.dumps(obj, indent=2, ensure_ascii=False)
        except Exception:
            return read_text_file(path)
    if ext in TEXT_LIKE_EXTS or ext in {".doc", ".ppt", ".xls"}:
        # Legacy Office binary formats are best-effort decode only.
        return read_text_file(path)
    # Generic fallback for unknown files that are actually text.
    return read_text_file(path)


def should_ignore(path: Path) -> bool:
    if path.name.lower() in IGNORE_FILENAMES:
        return True
    return any(part.lower() in IGNORE_DIRNAMES for part in path.parts)


def folder_chain(relative_path: Path) -> list[str]:
    folders = [sanitize_name(p) for p in relative_path.parts[:-1]]
    return folders if folders else ["TOP LEVEL"]


def local_clean_zip_name(raw_name: str) -> str:
    name = Path(raw_name).stem
    name = re.sub(r"\(\d+\)$", "", name).strip()
    name = re.sub(r"\b\d{1,2}[:\-]\d{2}\s*(AM|PM)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\b\d{5,}\b", "", name)
    name = re.sub(r"\s+-\s+", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    words = name.split()
    if len(words) > 8:
        name = " ".join(words[:8])
    return sanitize_name(name) or "Module Export"


def parse_response_output_text(resp: dict) -> str:
    text = (resp.get("output_text") or "").strip()
    if text:
        return text
    out = []
    for item in resp.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                t = (content.get("text") or "").strip()
                if t:
                    out.append(t)
    return " ".join(out).strip()


def ai_clean_zip_name(raw_zip_stem: str, api_key: str, model: str) -> str:
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": ZIP_NAME_PROMPT},
            {"role": "user", "content": raw_zip_stem},
        ],
        "max_output_tokens": 60,
        "temperature": 0,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    text = parse_response_output_text(data)
    return sanitize_name(text) if text else ""


def load_name_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_name_cache(path: Path, cache: dict[str, str]) -> None:
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_clean_zip_label(zip_path: Path, api_key: str, model: str, cache: dict[str, str]) -> tuple[str, str]:
    key = zip_path.stem
    if key in cache and cache[key].strip():
        return sanitize_name(cache[key]), "cache"

    label = ""
    used_api = False
    if api_key:
        try:
            label = ai_clean_zip_name(key, api_key, model)
            used_api = bool(label)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            label = ""
        except Exception:
            label = ""

    if not label:
        label = local_clean_zip_name(key)

    cache[key] = label
    return label, ("api" if used_api else "fallback")


def collect_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and not should_ignore(p):
            yield p


def is_probably_text_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in {".html", ".htm", ".xhtml", ".txt", ".md", ".markdown", ".xml", ".json", ".csv", ".tsv"}:
        return True
    if ext in {".js", ".mjs", ".cjs", ".css"}:
        return True
    return False


def classify_media_url(url: str, context: str) -> Optional[str]:
    u = url.lower()
    c = context.lower()
    is_video_host = bool(VIDEO_HINT_RE.search(u))
    is_ppt_file = u.endswith((".ppt", ".pptx"))
    is_ppt = is_ppt_file or "powerpoint" in u or "slides" in u or bool(PPT_HINT_RE.search(c))
    is_video = (
        u.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm", ".m3u8"))
        or is_video_host
        or bool(VIDEO_HINT_RE.search(c))
    )
    # Prefer video classification for known video hosts (e.g., Panopto),
    # unless the URL is explicitly a PowerPoint file.
    if is_video and (is_video_host or not is_ppt_file):
        return "Video/embedded media link"
    if is_ppt:
        return "PowerPoint link"
    return None


def clean_snippet(text: str, max_len: int = 180) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) > max_len:
        s = "..." + s[-max_len:]
    return s


def html_to_plain_text_fragment(fragment: str) -> str:
    parser = HTMLToTextParser()
    parser.feed(fragment)
    parser.close()
    return parser.get_text()


class HTMLLinkContextParser(HTMLParser):
    def __init__(self, rel: Path) -> None:
        super().__init__()
        self.rel = rel
        self.text_parts: list[str] = []
        self.detections: list[LinkDetection] = []
        self._seen: set[tuple[str, str, str]] = set()
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        t = tag.lower()
        if t in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if self._skip_depth > 0:
            return

        context = " ".join(self.text_parts[-20:])
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        for key in ("href", "src", "data-src", "data-url", "data"):
            url = attr_map.get(key, "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue
            kind = classify_media_url(url, f"{tag} {key} {context}")
            if not kind:
                continue
            det = LinkDetection(
                source=self.rel,
                kind=kind,
                url=url,
                snippet_before=clean_snippet(context),
            )
            sig = (str(det.source), det.kind, det.url)
            if sig not in self._seen:
                self._seen.add(sig)
                self.detections.append(det)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        t = tag.lower()
        if t in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._skip_depth == 0:
            cleaned = clean_snippet(data, max_len=500)
            if cleaned:
                self.text_parts.append(cleaned)


def detect_external_downloads_from_html(raw: str, rel: Path) -> list[LinkDetection]:
    parser = HTMLLinkContextParser(rel)
    parser.feed(raw)
    parser.close()
    return parser.detections


def detect_external_downloads_from_original(src: Path, rel: Path) -> list[LinkDetection]:
    if not is_probably_text_file(src):
        return []
    try:
        raw = read_text_file(src)
    except Exception:
        return []
    if not raw.strip():
        return []
    is_html = src.suffix.lower() in {".html", ".htm", ".xhtml"}
    if is_html:
        return detect_external_downloads_from_html(raw, rel)

    # Focus on links that imply a separate destination.
    hits: list[LinkDetection] = []
    seen: set[tuple[str, str, str]] = set()
    context_window = 120
    for m in URL_RE.finditer(raw):
        url = m.group(0).rstrip(").,;\"'")
        if not url:
            continue
        start = max(0, m.start() - context_window)
        end = min(len(raw), m.end() + context_window)
        ctx = raw[start:end]
        kind = classify_media_url(url, ctx)
        if not kind:
            continue
        before = raw[max(0, m.start() - 220) : m.start()]
        snippet = clean_snippet(before)
        key = (str(rel), kind, url)
        if key not in seen:
            seen.add(key)
            hits.append(LinkDetection(source=rel, kind=kind, url=url, snippet_before=snippet))
    return hits


def process_zip(zip_path: Path, output_root: Path, zip_label: str) -> tuple[list[FileResult], list[LinkDetection]]:
    results: list[FileResult] = []
    detections_all: list[LinkDetection] = []
    detections_seen: set[tuple[str, str, str]] = set()
    with tempfile.TemporaryDirectory(prefix="now_extract_") as td:
        extract_dir = Path(td)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        for src in collect_files(extract_dir):
            rel = src.relative_to(extract_dir)
            chain = [zip_label] + folder_chain(rel)

            raw_name = sanitize_name(src.name)
            ext = src.suffix.lower()
            stem = sanitize_name(Path(raw_name).stem)
            base = sanitize_name(" - ".join(chain + [stem]))
            detections = detect_external_downloads_from_original(src, rel)
            for d in detections:
                k = (str(d.source), d.kind, d.url)
                if k not in detections_seen:
                    detections_seen.add(k)
                    detections_all.append(d)

            if ext in IMAGE_EXTS:
                results.append(FileResult(source=rel, output=None, action="deleted", note="image removed"))
                continue

            if ext in SUPPORTED_NOTEBOOKLM_EXTS:
                out = unique_path(output_root / f"{base}{ext}")
                shutil.copy2(src, out)
                if is_within_notebooklm_size_limit(out):
                    results.append(FileResult(source=rel, output=out, action="copied"))
                else:
                    out.unlink(missing_ok=True)
                    results.append(
                        FileResult(
                            source=rel,
                            output=None,
                            action="skipped",
                            note=f"{ext} exceeds NotebookLM 200MB limit",
                        )
                    )
                continue

            if ext == ".pptx":
                pdf_path = convert_pptx_to_pdf(src)
                if pdf_path and is_within_notebooklm_size_limit(pdf_path):
                    out = unique_path(output_root / f"{base}.pdf")
                    shutil.copy2(pdf_path, out)
                    results.append(FileResult(source=rel, output=out, action="converted", note=".pptx -> .pdf"))
                    continue
                if pdf_path and pdf_path.exists():
                    pdf_path.unlink(missing_ok=True)

            # Convert unsupported to txt where possible.
            try:
                text = convert_to_text(src).strip()
                if not text:
                    raise ValueError("empty text after conversion")
                out = unique_path(output_root / f"{base}.txt")
                out.write_text(text + "\n", encoding="utf-8")
                note = f"{ext or '[no-ext]'} -> .txt"
                if ext == ".pptx":
                    note = ".pptx -> .txt (PDF missing or over NotebookLM limit)"
                results.append(FileResult(source=rel, output=out, action="converted", note=note))
            except Exception as exc:
                results.append(FileResult(source=rel, output=None, action="skipped", note=str(exc)))

    return results, detections_all


def similarity_key_for_merge(path: Path) -> str:
    name = path.stem.lower()
    name = re.sub(r"\(\d+\)$", "", name).strip()
    name = re.sub(
        r"\b(week|wk|lecture|seminar|session|part|module|chapter|lesson)\s*[-_ ]*\d+\b",
        r"\1 #",
        name,
    )
    name = re.sub(r"\b\d+\b", "#", name)
    name = re.sub(r"#+", "#", name)
    name = re.sub(r"[_\-.]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def smart_merge_rule_for_file(path: Path) -> Optional[tuple[str, str]]:
    if path.suffix.lower() not in MERGEABLE_EXTS:
        return None

    name = path.stem.lower()
    name = re.sub(r"\s*\(\d+\)$", "", name).strip()
    name = re.sub(r"\s+", " ", name)

    if "table of contents" in name:
        return ("smart_table_of_contents", "table-of-contents-pack")

    if re.search(r"\bpre[- ]?work\b", name):
        return ("smart_prework_pack", "pre-work-pack")

    if re.search(r"\bhomework\b", name):
        return ("smart_homework_pack", "homework-pack")

    if "lecture" in name:
        return ("smart_lecture_pack", "lecture-navigation-pack")

    return None


def collect_smart_merge_groups(paths: list[Path], min_group: int) -> list[tuple[str, str, list[Path]]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    labels: dict[str, str] = {}
    for p in paths:
        match = smart_merge_rule_for_file(p)
        if not match:
            continue
        key, label = match
        grouped[key].append(p)
        labels[key] = label

    groups: list[tuple[str, str, list[Path]]] = []
    for key in sorted(grouped):
        files = sorted(grouped[key], key=merge_sort_key)
        if len(files) >= min_group:
            groups.append((key, labels[key], files))
    return groups


def tokenize_for_similarity(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    tokens = [t for t in normalized.split() if len(t) >= 3 and not t.isdigit()]
    return set(tokens[:8000])


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def merge_sort_key(path: Path) -> tuple[int, list[int], str]:
    nums = [int(n) for n in re.findall(r"\d+", path.stem)]
    return (nums[0] if nums else 10**9, nums, path.name.lower())


def average_similarity_from_files(paths: list[Path]) -> float:
    token_cache: dict[Path, set[str]] = {}
    usable: list[Path] = []
    for p in paths:
        try:
            tokens = tokenize_for_similarity(read_text_file(p))
        except Exception:
            tokens = set()
        token_cache[p] = tokens
        if tokens:
            usable.append(p)
    if len(usable) < 2:
        return 0.0
    return average_pairwise_similarity(usable, token_cache)


def average_pairwise_similarity(paths: list[Path], token_cache: dict[Path, set[str]]) -> float:
    if len(paths) < 2:
        return 1.0
    total = 0.0
    pairs = 0
    for i, a in enumerate(paths):
        for b in paths[i + 1 :]:
            total += jaccard_similarity(token_cache[a], token_cache[b])
            pairs += 1
    if pairs == 0:
        return 0.0
    return total / pairs


def find_similar_components(
    paths: list[Path],
    token_cache: dict[Path, set[str]],
    threshold: float,
    min_group: int,
) -> list[tuple[list[Path], float]]:
    n = len(paths)
    adjacency: dict[int, set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(token_cache[paths[i]], token_cache[paths[j]])
            if sim >= threshold:
                adjacency[i].add(j)
                adjacency[j].add(i)

    components: list[tuple[list[Path], float]] = []
    seen: set[int] = set()
    for i in range(n):
        if i in seen:
            continue
        stack = [i]
        comp_idxs: list[int] = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp_idxs.append(cur)
            stack.extend(adjacency[cur] - seen)
        if len(comp_idxs) < min_group:
            continue
        comp_paths = sorted((paths[idx] for idx in comp_idxs), key=merge_sort_key)
        avg_sim = average_pairwise_similarity(comp_paths, token_cache)
        components.append((comp_paths, avg_sim))
    return components


def merge_group_to_output(
    output_root: Path,
    pattern: str,
    output_label: str,
    source_files: list[Path],
    threshold: float,
    keep_sources: bool,
    strategy: str,
) -> MergeGroupSummary:
    merged_label = sanitize_name(output_label)
    merged_path = unique_path(output_root / f"{merged_label} - MERGED.txt")
    avg_sim = average_similarity_from_files(source_files)
    merged_text = build_merged_file_text(pattern, source_files, avg_sim, threshold)
    merged_path.write_text(merged_text, encoding="utf-8")

    removed = 0
    if not keep_sources:
        for src in source_files:
            try:
                src.unlink()
                removed += 1
            except Exception:
                continue

    return MergeGroupSummary(
        pattern=pattern,
        merged_file=merged_path,
        source_files=source_files,
        avg_similarity=avg_sim,
        removed_sources=removed,
        strategy=strategy,
    )


def merge_label_from_pattern(pattern: str, source_files: list[Path]) -> str:
    label = pattern.replace("#", "series")
    label = sanitize_name(label)
    if len(label) > 80:
        label = label[:80].rstrip()
    if label:
        return label
    if source_files:
        return sanitize_name(source_files[0].stem)
    return "merged-similar-files"


def build_merged_file_text(
    pattern: str,
    source_files: list[Path],
    avg_similarity: float,
    threshold: float,
) -> str:
    lines = [
        "Merged similar files for NotebookLM source reduction.",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Similarity key: {pattern}",
        f"Similarity threshold: {threshold:.2f}",
        f"Average pairwise similarity: {avg_similarity:.3f}",
        "",
        "Source files:",
    ]
    for p in source_files:
        lines.append(f"- {p.name}")
    lines.append("")

    for idx, src in enumerate(source_files, start=1):
        lines.append("=" * 84)
        lines.append(f"[{idx}/{len(source_files)}] {src.name}")
        lines.append("=" * 84)
        try:
            content = read_text_file(src).strip()
        except Exception as exc:
            content = f"[read failed: {exc}]"
        lines.append(content if content else "[empty file]")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def merge_similar_output_files(
    output_root: Path,
    threshold: float,
    min_group: int,
    keep_sources: bool,
) -> list[MergeGroupSummary]:
    candidates = [
        p
        for p in sorted(output_root.iterdir())
        if p.is_file() and p.suffix.lower() in MERGEABLE_EXTS
    ]
    merged_groups: list[MergeGroupSummary] = []
    used_paths: set[Path] = set()

    # 1) Deterministic smart rules for common academic export patterns.
    for key, label, group in collect_smart_merge_groups(candidates, min_group):
        group_paths = [p for p in group if p not in used_paths]
        if len(group_paths) < min_group:
            continue
        merged_groups.append(
            merge_group_to_output(
                output_root=output_root,
                pattern=f"smart-rule:{key}",
                output_label=label,
                source_files=group_paths,
                threshold=threshold,
                keep_sources=keep_sources,
                strategy="smart-rule",
            )
        )
        used_paths.update(group_paths)

    # 2) Similarity fallback for everything not handled by smart rules.
    remaining = [p for p in candidates if p not in used_paths]
    by_key: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for p in remaining:
        by_key[(p.suffix.lower(), similarity_key_for_merge(p))].append(p)

    token_cache: dict[Path, set[str]] = {}
    for (_ext, pattern), group in sorted(by_key.items(), key=lambda item: (item[0][1], item[0][0])):
        if len(group) < min_group:
            continue

        valid_paths: list[Path] = []
        for p in group:
            try:
                tokens = tokenize_for_similarity(read_text_file(p))
            except Exception:
                tokens = set()
            token_cache[p] = tokens
            if tokens:
                valid_paths.append(p)
        if len(valid_paths) < min_group:
            continue

        for component, _avg_sim in find_similar_components(
            sorted(valid_paths, key=merge_sort_key),
            token_cache,
            threshold,
            min_group,
        ):
            merged_label = merge_label_from_pattern(pattern, component)
            merged_groups.append(
                merge_group_to_output(
                    output_root=output_root,
                    pattern=pattern,
                    output_label=merged_label,
                    source_files=component,
                    threshold=threshold,
                    keep_sources=keep_sources,
                    strategy="similarity",
                )
            )
            used_paths.update(component)

    return merged_groups


def write_merge_report(
    summary_dir: Path,
    groups: list[MergeGroupSummary],
    threshold: float,
    min_group: int,
    keep_sources: bool,
) -> Path:
    out = summary_dir / "_merged_similar_report.txt"
    lines = [
        "Similar-File Merge Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Similarity threshold: {threshold:.2f}",
        f"Minimum group size: {min_group}",
        f"Keep originals: {'yes' if keep_sources else 'no'}",
        f"Merged groups: {len(groups)}",
        f"Total source files removed: {sum(g.removed_sources for g in groups)}",
        "",
    ]

    if not groups:
        lines.append("No merge groups found.")
    else:
        for idx, g in enumerate(groups, start=1):
            lines.append(f"[{idx}] {g.merged_file.name}")
            lines.append(f"    strategy: {g.strategy}")
            lines.append(f"    pattern: {g.pattern}")
            lines.append(f"    avg_similarity: {g.avg_similarity:.3f}")
            lines.append(f"    removed_sources: {g.removed_sources}")
            lines.append("    source_files:")
            for src in g.source_files:
                lines.append(f"      - {src.name}")
            lines.append("")

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def write_report(
    output_root: Path,
    zip_index: int,
    zip_name: str,
    zip_label: str,
    results: list[FileResult],
    detections: list[LinkDetection],
) -> None:
    converted = sum(1 for r in results if r.action == "converted")
    copied = sum(1 for r in results if r.action == "copied")
    deleted = sum(1 for r in results if r.action == "deleted")
    skipped = [r for r in results if r.action == "skipped"]

    lines = [
        f"Zip: {zip_name}",
        f"Zip label: {zip_label}",
        f"Copied supported: {copied}",
        f"Converted to txt: {converted}",
        f"Images removed: {deleted}",
        f"Detections (external PPT/video links): {len(detections)}",
        f"Skipped: {len(skipped)}",
        "",
    ]

    if detections:
        lines.append("Detections:")
        for d in detections:
            lines.append(f"- {d.source} :: {d.kind} :: {d.url}")
            if d.snippet_before:
                lines.append(f"  context: {d.snippet_before}")
        lines.append("")

    if skipped:
        lines.append("Skipped files:")
        for r in skipped:
            lines.append(f"- {r.source} :: {r.note}")

    report_name = sanitize_name(f"_conversion_report - {zip_index:03d} - {zip_label}.txt")
    (output_root / report_name).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def section_id(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or "section"


def write_summary_html(
    output_root: Path,
    summaries: list[ZipRunSummary],
    prompt_text: str,
    model: str,
    merge_groups: Optional[list[MergeGroupSummary]] = None,
    merge_enabled: bool = False,
    merge_threshold: float = 0.18,
    merge_min_group: int = 2,
    keep_merged_sources: bool = False,
) -> Path:
    summary_dir = output_root / "SUMMARY"
    summary_dir.mkdir(parents=True, exist_ok=True)
    out = summary_dir / "SUMMARY.html"

    merge_groups = merge_groups or []
    total_copied = sum(s.copied for s in summaries)
    total_converted = sum(s.converted for s in summaries)
    total_deleted = sum(s.deleted for s in summaries)
    total_skipped = sum(s.skipped for s in summaries)
    total_detections = sum(len(s.detections) for s in summaries)
    total_merged_groups = len(merge_groups)
    total_merged_sources = sum(len(g.source_files) for g in merge_groups)
    total_sources_removed = sum(g.removed_sources for g in merge_groups)
    final_documents = sum(1 for p in output_root.iterdir() if p.is_file())

    nav_items: list[str] = []
    sections: list[str] = []
    summaries_sorted = sorted(summaries, key=lambda s: (-len(s.detections), s.zip_name.lower()))

    for s in summaries_sorted:
        sid = section_id(s.zip_name)
        nav_items.append(f'<a href="#{sid}">{html.escape(s.zip_name)}</a>')

        skipped_html = "<li>None</li>"
        if s.skipped_items:
            skipped_html = "".join(f"<li>{html.escape(item)}</li>" for item in s.skipped_items)
        detections_html = "<tr><td colspan=\"4\">None</td></tr>"
        if s.detections:
            detections_html = "".join(
                "<tr>"
                f"<td>{html.escape(str(d.source))}</td>"
                f"<td>{html.escape(d.kind)}</td>"
                f"<td><a href=\"{html.escape(d.url)}\" target=\"_blank\" rel=\"noopener noreferrer\">{html.escape(d.url)}</a></td>"
                f"<td>{html.escape(d.snippet_before or '-')}</td>"
                "</tr>"
                for d in s.detections
            )

        sections.append(
            f"""
            <section id="{sid}" class="card">
              <h3>{html.escape(s.zip_name)}</h3>
              <p><strong>Output Label:</strong> {html.escape(s.zip_label)} <span class="chip">{html.escape(s.label_source)}</span></p>
              <div class="stats">
                <span>Copied: {s.copied}</span>
                <span>Converted: {s.converted}</span>
                <span>Images Removed: {s.deleted}</span>
                <span>Detections: {len(s.detections)}</span>
                <span>Skipped: {s.skipped}</span>
              </div>
              <details>
                <summary>External PPT/Video Detections</summary>
                <div class="table-wrap">
                  <table class="det-table">
                    <thead>
                      <tr><th>Source File</th><th>Type</th><th>Link</th><th>Text Before Link</th></tr>
                    </thead>
                    <tbody>{detections_html}</tbody>
                  </table>
                </div>
              </details>
              <details>
                <summary>Skipped Files</summary>
                <ul>{skipped_html}</ul>
              </details>
            </section>
            """
        )

    merge_cards = (
        "<p class=\"empty-state\">No similar groups matched the current threshold. "
        "Lower the threshold if you want more aggressive merging.</p>"
    )
    if merge_groups:
        merge_cards = "".join(
            f"""
            <article class="merge-item">
              <div class="merge-item-head">
                <h3>{html.escape(g.merged_file.name)}</h3>
                <span class="merge-score">Avg Similarity {g.avg_similarity:.3f}</span>
              </div>
              <div class="stats merge-stats">
                <span>Sources: {len(g.source_files)}</span>
                <span>Removed: {g.removed_sources}</span>
                <span>Strategy: {html.escape(g.strategy)}</span>
                <span>Pattern: {html.escape(g.pattern)}</span>
              </div>
              <div class="file-chip-row">
                {"".join(f'<span class="file-chip">{html.escape(p.name)}</span>' for p in g.source_files)}
              </div>
            </article>
            """
            for g in merge_groups
        )

    merge_status_class = "merge-on" if merge_enabled else "merge-off"
    merge_status_text = "Enabled" if merge_enabled else "Disabled"

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NOW Cleanup Summary</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #f2f6f2;
      --card: rgba(255, 255, 255, 0.88);
      --ink: #142325;
      --muted: #4f6568;
      --accent: #087666;
      --accent-strong: #05584e;
      --line: #d0ddd6;
      --warm-soft: #fff4db;
      --ok: #d7f5ea;
      --ok-ink: #0a5a4f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Manrope", "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 0%, #d9f0ea, transparent 42%),
        radial-gradient(circle at 85% 8%, #ffe9c8, transparent 35%),
        linear-gradient(165deg, #f7fbf8 0%, #edf5ef 45%, #f6f2e9 100%),
        var(--bg);
      min-height: 100vh;
    }}
    .wrap {{ max-width: 1140px; margin: 0 auto; padding: 28px 18px 52px; }}
    .hero {{
      background:
        linear-gradient(135deg, rgba(8, 118, 102, 0.94), rgba(5, 88, 78, 0.95)),
        radial-gradient(circle at 85% 20%, rgba(245, 158, 11, 0.2), transparent 40%);
      color: #f6fffd;
      border-radius: 20px;
      padding: 22px 22px 18px;
      margin-bottom: 14px;
      border: 1px solid rgba(255, 255, 255, 0.24);
      box-shadow: 0 22px 48px rgba(6, 67, 60, 0.22);
      animation: rise 480ms ease;
    }}
    .hero-kicker {{
      margin: 0 0 8px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 11px;
      opacity: 0.9;
    }}
    h1 {{
      margin: 0;
      font-family: "Fraunces", Georgia, serif;
      font-size: clamp(28px, 4vw, 42px);
      letter-spacing: 0.01em;
      line-height: 1.08;
    }}
    .hero-subtitle {{
      margin: 8px 0 0;
      opacity: 0.94;
      font-size: 14px;
    }}
    .hero-meta {{
      margin-top: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .hero-meta span {{
      border: 1px solid rgba(255, 255, 255, 0.3);
      border-radius: 999px;
      padding: 6px 11px;
      font-size: 12px;
      background: rgba(255, 255, 255, 0.1);
      backdrop-filter: blur(4px);
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      margin-bottom: 14px;
      box-shadow: 0 12px 34px rgba(14, 41, 40, 0.07);
      backdrop-filter: blur(3px);
      animation: rise 520ms ease;
    }}
    h2 {{
      margin: 0 0 12px;
      font-family: "Fraunces", Georgia, serif;
      font-size: clamp(20px, 2.6vw, 28px);
      letter-spacing: 0.01em;
    }}
    h3 {{
      margin: 0 0 8px;
      font-family: "Fraunces", Georgia, serif;
      font-size: 20px;
      line-height: 1.2;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
      gap: 10px;
    }}
    .kpi {{
      background: #fcfffd;
      border: 1px solid #dbe9e1;
      border-radius: 12px;
      padding: 10px;
      display: grid;
      gap: 2px;
    }}
    .kpi .label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    .kpi .value {{
      font-size: 26px;
      line-height: 1;
      font-weight: 800;
      color: var(--accent-strong);
    }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 10px 0;
    }}
    .stats span {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 11px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.01em;
      background: #f6fbf9;
    }}
    .chip {{
      background: var(--ok);
      color: var(--ok-ink);
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      margin-left: 8px;
      font-weight: 700;
    }}
    .merge-status {{
      margin-left: 0;
      border: 1px solid transparent;
    }}
    .merge-status.merge-on {{
      background: var(--ok);
      color: var(--ok-ink);
      border-color: #bde8d8;
    }}
    .merge-status.merge-off {{
      background: var(--warm-soft);
      color: #8a5208;
      border-color: #f8d9a2;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0 18px;
    }}
    nav a {{
      text-decoration: none;
      color: var(--accent);
      border: 1px solid #bfded7;
      padding: 7px 12px;
      border-radius: 999px;
      background: #f0fcf8;
      font-size: 12px;
      font-weight: 700;
      transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease;
    }}
    nav a:hover {{
      background: #e2f7f1;
      transform: translateY(-1px);
      box-shadow: 0 8px 18px rgba(8, 118, 102, 0.16);
    }}
    pre {{
      white-space: pre-wrap;
      word-wrap: break-word;
      background: #f7fbfb;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px;
      font-size: 13px;
      line-height: 1.5;
    }}
    details {{
      margin-top: 10px;
      border: 1px solid #d8e4de;
      border-radius: 10px;
      background: #fbfffd;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      padding: 10px 12px;
    }}
    details[open] summary {{
      border-bottom: 1px solid #e0ebe6;
      background: #f4fcf8;
    }}
    details > ul,
    details > .table-wrap {{
      margin: 0;
      padding: 10px 12px 12px;
    }}
    ul {{ margin-top: 8px; }}
    .table-wrap {{ overflow-x: auto; margin-top: 8px; }}
    .det-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      border-radius: 10px;
      overflow: hidden;
    }}
    .det-table th, .det-table td {{ border: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    .det-table th {{ background: #eef7f3; font-weight: 700; }}
    .det-table tbody tr:nth-child(even) {{ background: #fbfefd; }}
    .det-table a {{ color: var(--accent); word-break: break-all; }}
    .merge-panel {{
      border: 1px solid #cbe0d8;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(244, 251, 248, 0.95));
    }}
    .merge-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .merge-grid {{
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }}
    .merge-item {{
      border: 1px solid #d4e6de;
      border-radius: 12px;
      padding: 12px;
      background: #ffffff;
      box-shadow: 0 8px 18px rgba(12, 53, 48, 0.07);
      animation: rise 620ms ease both;
    }}
    .merge-item-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }}
    .merge-item-head h3 {{
      margin: 0;
      font-size: 19px;
    }}
    .merge-score {{
      background: #e4f8f1;
      color: #0a5f52;
      border: 1px solid #bde7da;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .merge-stats {{
      margin: 4px 0 8px;
    }}
    .file-chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .file-chip {{
      background: #f5faf8;
      border: 1px solid #d8e8df;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      line-height: 1.3;
    }}
    .empty-state {{
      margin: 8px 0 0;
      padding: 11px 12px;
      border-radius: 10px;
      border: 1px dashed #cfddd6;
      background: #f9fdfb;
      color: var(--muted);
      font-size: 13px;
    }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(10px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @media (max-width: 860px) {{
      .wrap {{ padding: 16px 12px 34px; }}
      .hero {{ padding: 16px 15px; border-radius: 16px; }}
      .card {{ padding: 14px; }}
      .kpi .value {{ font-size: 22px; }}
      .merge-item-head h3 {{ font-size: 17px; }}
      .det-table {{ min-width: 680px; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <p class="hero-kicker">NotebookLM Preparation</p>
      <h1>NOW Cleanup Summary</h1>
      <p class="hero-subtitle">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</p>
      <div class="hero-meta">
        <span>{len(summaries)} zip exports</span>
        <span>{final_documents} final output documents</span>
        <span>{total_merged_groups} merge groups</span>
      </div>
    </section>

    <section class="card">
      <h2>Overall Pipeline</h2>
      <div class="kpi-grid">
        <article class="kpi"><span class="label">Zips</span><span class="value">{len(summaries)}</span></article>
        <article class="kpi"><span class="label">Copied</span><span class="value">{total_copied}</span></article>
        <article class="kpi"><span class="label">Converted</span><span class="value">{total_converted}</span></article>
        <article class="kpi"><span class="label">Images Removed</span><span class="value">{total_deleted}</span></article>
        <article class="kpi"><span class="label">Detections</span><span class="value">{total_detections}</span></article>
        <article class="kpi"><span class="label">Skipped</span><span class="value">{total_skipped}</span></article>
        <article class="kpi"><span class="label">Merged Groups</span><span class="value">{total_merged_groups}</span></article>
        <article class="kpi"><span class="label">Merged Sources</span><span class="value">{total_merged_sources}</span></article>
        <article class="kpi"><span class="label">Sources Removed</span><span class="value">{total_sources_removed}</span></article>
      </div>
    </section>

    <section class="card">
      <h2>ZIP Naming</h2>
      <p><strong>Model:</strong> {html.escape(model)}</p>
      <p><strong>Prompt used:</strong></p>
      <pre>{html.escape(prompt_text)}</pre>
      <details>
        <summary>Labels Per ZIP</summary>
        <ul>
          {"".join(f"<li><strong>{html.escape(s.zip_name)}</strong> -> {html.escape(s.zip_label)} ({html.escape(s.label_source)})</li>" for s in summaries)}
        </ul>
      </details>
    </section>

    <section class="card merge-panel">
      <div class="merge-header">
        <h2>Similar-File Merge</h2>
        <span class="chip merge-status {merge_status_class}">{merge_status_text}</span>
      </div>
      <div class="stats">
        <span>Threshold: {merge_threshold:.2f}</span>
        <span>Min Group: {merge_min_group}</span>
        <span>Keep Originals: {"yes" if keep_merged_sources else "no"}</span>
      </div>
      <div class="merge-grid">
        {merge_cards}
      </div>
    </section>

    <section class="card">
      <h2>Jump to Zip</h2>
      <nav>{"".join(nav_items)}</nav>
    </section>

    {"".join(sections)}
  </main>
</body>
</html>
"""
    out.write_text(html_doc, encoding="utf-8")
    return out


def write_name_cache_txt(path: Path, cache: dict[str, str]) -> None:
    lines = ["Zip Name Cache (for transparency)", ""]
    for raw, cleaned in sorted(cache.items()):
        lines.append(f"{raw} -> {cleaned}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_pipeline(args: argparse.Namespace, source_dir: Path, output_root: Path, final_root: Path, zip_files: list[Path], api_key: str) -> None:
    summary_dir = output_root / "SUMMARY"
    summary_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = Path("~/.config/now-cleaner").expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "zip_name_cache.json"
    name_cache = load_name_cache(cache_path)

    print(f"Source: {source_dir}")
    print(f"Output: {final_root}")
    print(f"Found {len(zip_files)} zip files.")
    zip_summaries: list[ZipRunSummary] = []
    global_detection_urls: set[str] = set()

    for idx, zip_path in enumerate(zip_files, start=1):
        print(f"[{idx}/{len(zip_files)}] Processing: {zip_path.name}")
        try:
            zip_label, label_source = get_clean_zip_label(zip_path, api_key, args.openai_model, name_cache)
            save_name_cache(cache_path, name_cache)
            results, detections = process_zip(zip_path, output_root, zip_label)
            # Deduplicate detections across all zips by URL.
            unique_global: list[LinkDetection] = []
            for d in detections:
                k = d.url.strip().lower()
                if k in global_detection_urls:
                    continue
                global_detection_urls.add(k)
                unique_global.append(d)
            detections = unique_global
            write_report(summary_dir, idx, zip_path.name, zip_label, results, detections)
            converted = sum(1 for r in results if r.action == "converted")
            copied = sum(1 for r in results if r.action == "copied")
            deleted = sum(1 for r in results if r.action == "deleted")
            skipped = sum(1 for r in results if r.action == "skipped")
            skipped_items = [f"{r.source} :: {r.note}" for r in results if r.action == "skipped"]
            zip_summaries.append(
                ZipRunSummary(
                    zip_name=zip_path.name,
                    zip_label=zip_label,
                    label_source=label_source,
                    copied=copied,
                    converted=converted,
                    deleted=deleted,
                    skipped=skipped,
                    skipped_items=skipped_items,
                    detections=detections,
                )
            )
            print(
                f"    zip_label={zip_label} copied={copied} converted={converted} "
                f"images_removed={deleted} detections={len(detections)} skipped={skipped}"
            )
        except zipfile.BadZipFile:
            print(f"    skipped (bad zip): {zip_path.name}")
            zip_summaries.append(
                ZipRunSummary(
                    zip_name=zip_path.name,
                    zip_label=local_clean_zip_name(zip_path.stem),
                    label_source="bad-zip",
                    copied=0,
                    converted=0,
                    deleted=0,
                    skipped=1,
                    skipped_items=["Bad zip file"],
                    detections=[],
                )
            )

    merge_groups: list[MergeGroupSummary] = []
    if args.merge_similar:
        merge_groups = merge_similar_output_files(
            output_root=output_root,
            threshold=args.merge_threshold,
            min_group=args.merge_min_group,
            keep_sources=args.keep_merged_sources,
        )
        merge_report_path = write_merge_report(
            summary_dir=summary_dir,
            groups=merge_groups,
            threshold=args.merge_threshold,
            min_group=args.merge_min_group,
            keep_sources=args.keep_merged_sources,
        )
        print(
            "Merge similar: "
            f"groups={len(merge_groups)} "
            f"sources_removed={sum(g.removed_sources for g in merge_groups)}"
        )
        print(f"Merge report: {final_root / 'SUMMARY' / merge_report_path.name}")

    summary_path = write_summary_html(
        output_root=output_root,
        summaries=zip_summaries,
        prompt_text=ZIP_NAME_PROMPT,
        model=args.openai_model,
        merge_groups=merge_groups,
        merge_enabled=args.merge_similar,
        merge_threshold=args.merge_threshold,
        merge_min_group=args.merge_min_group,
        keep_merged_sources=args.keep_merged_sources,
    )
    write_name_cache_txt(output_root / "SUMMARY" / "_zip_name_cache.txt", name_cache)
    print(f"Summary prepared: {summary_path.name}")


def main() -> int:
    args = parse_args()
    if not (0.0 <= args.merge_threshold <= 1.0):
        print("--merge-threshold must be between 0 and 1.", file=sys.stderr)
        return 1
    if args.merge_min_group < 2:
        print("--merge-min-group must be at least 2.", file=sys.stderr)
        return 1

    source_input = args.source_folder if args.source_folder else args.source
    source_dir = source_input.expanduser().resolve()
    if not source_dir.is_dir():
        print(f"Source folder not found: {source_dir}", file=sys.stderr)
        return 1
    try:
        output_root = resolve_output_root(source_dir, args.output_name or "")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    zip_files = sorted(p for p in source_dir.glob("*.zip") if p.is_file())
    if not zip_files:
        print(f"No zip files found in {source_dir}", file=sys.stderr)
        return 1
    if output_root.exists() or output_root.is_symlink():
        if not args.overwrite:
            print(f"Output folder already exists: {output_root}\nUse --overwrite to rebuild it.", file=sys.stderr)
            return 1
        if not is_managed_output(output_root, source_dir):
            print(f"Refusing to overwrite an unrecognised folder: {output_root}\nMove it aside manually first.", file=sys.stderr)
            return 1

    api_key = load_api_key(args.openai_api_key)
    with tempfile.TemporaryDirectory(prefix=".now-cleaner-", dir=source_dir.parent) as staging_name:
        staging = Path(staging_name)
        try:
            run_pipeline(args, source_dir, staging, output_root, zip_files, api_key)
            mark_output(staging, source_dir)
        except Exception as exc:
            print(f"Processing failed; previous output was preserved: {exc}", file=sys.stderr)
            return 1

        backup = source_dir.parent / f".now-cleaner-backup-{uuid4().hex}"
        had_previous = output_root.exists()
        try:
            if had_previous:
                output_root.rename(backup)
            staging.rename(output_root)
        except OSError as exc:
            if had_previous and backup.exists() and not output_root.exists():
                backup.rename(output_root)
            print(f"Could not publish output: {exc}", file=sys.stderr)
            return 1
        if had_previous:
            shutil.rmtree(backup)
    print(f"Summary: {output_root / 'SUMMARY' / 'SUMMARY.html'}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
