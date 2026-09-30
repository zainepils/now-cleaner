"""Create a fictional ZIP export for a safe NOW Cleaner demo."""

import sys
import zipfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/make_demo.py OUTPUT_FOLDER")
    folder = Path(sys.argv[1]).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "Fictional Project Planning.zip", "w") as archive:
        archive.writestr("Week 1/Overview.html", "<h1>Project Planning</h1><p>Define scope, risks and milestones.</p>")
        archive.writestr("Week 2/Notes.txt", "A fictional team reviews scope, risks and milestones.\n")
        archive.writestr("Week 3/Notes.txt", "A fictional team updates scope, risks and milestones.\n")
    print(folder)


if __name__ == "__main__":
    main()
