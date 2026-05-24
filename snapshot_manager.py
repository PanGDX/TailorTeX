import json
from pathlib import Path

SNAPSHOTS_DIR = "snapshots"
SNAPSHOT_INDEX_FILE = "snapshots/index.json"
GEN_PDF_DIR = "generated-pdfs"


def _ensure_dir():
    Path(SNAPSHOTS_DIR).mkdir(parents=True, exist_ok=True)


def save_snapshot(latex_code: str, timestamp: str) -> dict:
    """
    Saves the given LaTeX code to snapshots/<timestamp>.tex and records the
    entry in the JSON index.  The caller supplies the timestamp so that the
    .tex filename, the .pdf filename, and the index entry all share the same
    string and can be cross-referenced without any guesswork.

    Returns the new snapshot entry dict on success, raises on failure.
    """
    _ensure_dir()

    tex_filename = f"{timestamp}.tex"
    tex_filepath = f"{SNAPSHOTS_DIR}/{tex_filename}"
    pdf_filepath = f"{GEN_PDF_DIR}/{timestamp}.pdf"

    with open(tex_filepath, "w", encoding="utf-8") as f:
        f.write(latex_code)

    entry = {
        "timestamp": timestamp,
        "tex_filepath": tex_filepath,
        "pdf_filepath": pdf_filepath,
    }

    index = load_index()
    index.insert(0, entry)   # newest-first
    _write_index(index)

    return entry


def load_index() -> list[dict]:
    """
    Returns the full snapshot index as a list of dicts, newest-first.
    Returns an empty list if the index does not exist yet or is corrupted.
    """
    path = Path(SNAPSHOT_INDEX_FILE)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def load_snapshot_content(tex_filepath: str) -> str:
    """
    Reads and returns the LaTeX source for a given .tex filepath.
    Raises FileNotFoundError if the file is missing.
    """
    with open(tex_filepath, "r", encoding="utf-8") as f:
        return f.read()


def delete_snapshot(tex_filepath: str) -> None:
    """
    Deletes the .tex file and removes its entry from the index.
    The PDF in generated-pdfs/ is intentionally left on disk; it was
    produced by the compiler and may be wanted independently.
    """
    path = Path(tex_filepath)
    if path.exists():
        path.unlink()

    index = load_index()
    index = [e for e in index if e["tex_filepath"] != tex_filepath]
    _write_index(index)


# ---- Internal helpers ----

def _write_index(index: list[dict]) -> None:
    _ensure_dir()
    with open(SNAPSHOT_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
