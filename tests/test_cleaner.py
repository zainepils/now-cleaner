import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clean_now_notebooklm as cleaner


SCRIPT = Path(__file__).resolve().parents[1] / "clean_now_notebooklm.py"


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.env = {**os.environ, "HOME": str(self.root), "OPENAI_API_KEY": ""}

    def add_zip(self, name, files):
        with zipfile.ZipFile(self.source / name, "w") as archive:
            for path, content in files.items():
                archive.writestr(path, content)

    def run_cleaner(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--source", str(self.source), *extra],
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_refuses_unsafe_output_names(self):
        self.add_zip("One.zip", {"note.txt": "sample"})
        for name in ("source", "..", "../other", str(self.root)):
            with self.subTest(name=name):
                result = self.run_cleaner("--output-name", name, "--overwrite")
                self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.source / "One.zip").exists())

    def test_unmarked_folder_is_never_overwritten(self):
        self.add_zip("One.zip", {"note.txt": "sample"})
        output = self.root / "source - Cleaned and ready."
        output.mkdir()
        (output / "precious.txt").write_text("keep")
        result = self.run_cleaner("--overwrite")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((output / "precious.txt").read_text(), "keep")

    def test_reports_are_unique_and_managed_overwrite_works(self):
        self.add_zip("Module 1.zip", {"Week 1/a.html": "<p>First</p>"})
        self.add_zip("Module (1).zip", {"Week 2/b.html": "<p>Second</p>"})
        first = self.run_cleaner()
        self.assertEqual(first.returncode, 0, first.stderr)
        output = self.root / "source - Cleaned and ready."
        self.assertTrue((output / ".now-cleaner-output.json").exists())
        reports = list((output / "SUMMARY").glob("_conversion_report*.txt"))
        self.assertEqual(len(reports), 2)
        self.assertEqual(self.run_cleaner().returncode, 1)
        (output / "stale.txt").write_text("old")
        second = self.run_cleaner("--overwrite")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse((output / "stale.txt").exists())
        summary = (output / "SUMMARY" / "SUMMARY.html").read_text()
        self.assertIn("final output documents", summary)

    def test_failed_rebuild_preserves_previous_output(self):
        self.add_zip("One.zip", {"note.txt": "sample"})
        self.assertEqual(self.run_cleaner().returncode, 0)
        output = self.root / "source - Cleaned and ready."
        original = (output / "SUMMARY" / "SUMMARY.html").read_bytes()
        args = [str(SCRIPT), "--source", str(self.source), "--overwrite"]
        with mock.patch.object(sys, "argv", args), \
             mock.patch.object(cleaner, "load_api_key", return_value=""), \
             mock.patch.object(cleaner, "run_pipeline", side_effect=RuntimeError("synthetic failure")):
            self.assertEqual(cleaner.main(), 1)
        self.assertEqual((output / "SUMMARY" / "SUMMARY.html").read_bytes(), original)

    def test_no_zips_creates_no_output(self):
        self.assertEqual(self.run_cleaner().returncode, 1)
        self.assertFalse((self.root / "source - Cleaned and ready.").exists())

    def test_pptx_is_preserved_even_with_merging(self):
        payload = b"synthetic presentation bytes\x00\xff"
        self.add_zip("Slides.zip", {"Week 1/lecture.PPTX": payload})
        original_zip = (self.source / "Slides.zip").read_bytes()
        result = self.run_cleaner("--merge-similar")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / "source - Cleaned and ready."
        presentations = list(output.glob("*.pptx"))
        self.assertEqual(len(presentations), 1)
        self.assertEqual(presentations[0].read_bytes(), payload)
        self.assertIn("Week 1", presentations[0].name)
        self.assertFalse(list(output.glob("*.pdf")))
        self.assertFalse(list(output.glob("*.txt")))
        self.assertEqual((self.source / "Slides.zip").read_bytes(), original_zip)
        reports = list((output / "SUMMARY").glob("_conversion_report*.txt"))
        self.assertIn("Copied supported: 1", reports[0].read_text())

    def test_oversized_pptx_is_skipped_not_converted(self):
        self.add_zip("Slides.zip", {"lecture.pptx": b"synthetic presentation"})
        output = self.root / "output"
        output.mkdir()
        with mock.patch.object(cleaner, "NOTEBOOKLM_MAX_FILE_BYTES", 4):
            results, _ = cleaner.process_zip(self.source / "Slides.zip", output, "Slides")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "skipped")
        self.assertIn("200MB", results[0].note)
        self.assertFalse(list(output.iterdir()))

    def test_epub_and_supported_images_are_preserved(self):
        extensions = sorted(cleaner.SUPPORTED_IMAGE_EXTS | {".epub"})
        files = {f"Week 1/sample{ext.upper()}": b"synthetic bytes\x00\xff" for ext in extensions}
        files["Week 1/icon.svg"] = "<svg/>"
        self.add_zip("Resources.zip", files)
        result = self.run_cleaner("--merge-similar")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / "source - Cleaned and ready."
        for ext in extensions:
            with self.subTest(ext=ext):
                matches = list(output.glob(f"*{ext}"))
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].read_bytes(), b"synthetic bytes\x00\xff")
        self.assertFalse(list(output.glob("*.svg")))
        self.assertFalse(list(output.glob("*.txt")))

    def test_exclude_images_keeps_epub(self):
        self.add_zip("Resources.zip", {"diagram.png": b"image", "book.epub": b"ebook"})
        result = self.run_cleaner("--exclude-images")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.root / "source - Cleaned and ready."
        self.assertFalse(list(output.glob("*.png")))
        self.assertEqual(len(list(output.glob("*.epub"))), 1)
        reports = list((output / "SUMMARY").glob("_conversion_report*.txt"))
        self.assertIn("Images removed: 1", reports[0].read_text())

    def test_oversized_epub_and_image_are_skipped(self):
        self.add_zip("Resources.zip", {"book.epub": b"ebook", "diagram.png": b"image"})
        output = self.root / "output"
        output.mkdir()
        with mock.patch.object(cleaner, "NOTEBOOKLM_MAX_FILE_BYTES", 4):
            results, _ = cleaner.process_zip(self.source / "Resources.zip", output, "Resources")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.action == "skipped" for result in results))
        self.assertFalse(list(output.iterdir()))

    def test_desktop_image_option_reaches_backend(self):
        import now_cleaner_desktop as desktop
        app = desktop.CleanerApp.__new__(desktop.CleanerApp)
        app.keep_images_var = mock.Mock()
        for keep in (True, False):
            app.keep_images_var.get.return_value = keep
            command = app._build_command(self.source, "", False, False)
            self.assertEqual("--exclude-images" in command, not keep)


if __name__ == "__main__":
    unittest.main()
