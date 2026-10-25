"""Guards for the English-only product policy.

The legacy ``dao/`` tree is exempt until the M4 cutover. Everything in the new
engine, the add-on scaffold, and the top-level metadata must be English.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SHIPPED_PATHS = [
    ROOT / "src" / "daeo",
    ROOT / "custom_components",
    ROOT / "addon",
    ROOT / "README.md",
    ROOT / "repository.yaml",
    ROOT / "pyproject.toml",
    ROOT / "addon" / "config.yaml",
]

TEXT_SUFFIXES = {".py", ".html", ".md", ".yaml", ".yml", ".toml", ".sh", ".css", ".js"}

# Common Dutch words that should never appear in shipped English text. The list is
# deliberately small to avoid false positives on English words.
DUTCH_TERMS = [
    "berekening",
    "bestand",
    "beschikbaar",
    "dag",
    "fout",
    "gebruik",
    "gegevens",
    "jaar",
    "maand",
    "morgen",
    "niet",
    "opgehaald",
    "productie",
    "tijd",
    "uur",
    "vandaag",
    "verbruik",
    "waarde",
    "wordt",
    "worden",
    "zonder",
]


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for entry in SHIPPED_PATHS:
        if entry.is_file():
            files.append(entry)
        elif entry.is_dir():
            files.extend(
                path
                for path in entry.rglob("*")
                if path.is_file() and path.suffix in TEXT_SUFFIXES
            )
    return files


def test_shipped_text_contains_no_dutch_terms() -> None:
    offenders: list[str] = []
    for path in _iter_text_files():
        text = path.read_text(encoding="utf-8")
        for term in DUTCH_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}: {term}")
    assert not offenders, "Dutch terms in shipped English files:\n" + "\n".join(offenders)


def test_shipped_text_has_no_legacy_cjk_character() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in _iter_text_files()
        if "\u5200" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"Legacy character found in: {offenders}"
