"""
Scan tracked text files for invisible Unicode used to smuggle instructions.

The knowledge base ingests text the repo did not author — fetched pages, pasted
conversations, AI transcripts distilled into `daily/` and compiled into
`knowledge/`. Compiled articles are then auto-injected as trusted context on
every session. That path turns any invisible payload into a durable one: it does
not have to win on the turn it arrives, it only has to survive compilation.

This check closes the cheapest part of that gap. It finds codepoints that render
as nothing (or as direction changes) in an editor and a review diff, but which a
model still consumes as tokens.

Detection only — it never rewrites a file. Stripping invisible characters from
prose is destructive and context-dependent, so remediation stays manual.

Usage:
    uv run python scripts/check-unicode-safety.py           # scan tracked files
    uv run python scripts/check-unicode-safety.py PATH ...  # scan specific paths

Exit status is 1 when any finding is reported, 0 when clean, so the check can
gate a hook or a future CI job.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# Codepoint ranges that carry no legitimate meaning in this repo's prose or
# code, paired with the reason each one is dangerous. The justification matters
# more than the range: a future reader must be able to tell whether a new
# entry belongs here, and whether an existing one is causing false positives.
#
# Each entry is (first, last, label, why).
DANGEROUS: list[tuple[int, int, str, str]] = [
    (
        0xE0000, 0xE007F, "tag characters",
        # Proposed for language tagging in Unicode 3.1, deprecated since 5.1.
        # No legitimate text uses them, which makes them the canonical vector
        # for "ASCII smuggling": an attacker encodes instructions as tag bytes
        # inside an ordinary-looking string, the model reads them, and the
        # human reviewer sees an unremarkable line.
        "deprecated since Unicode 5.1; the canonical ASCII-smuggling vector",
    ),
    (
        0x200B, 0x200D, "zero-width space/joiner",
        "renders as nothing; splits or hides words from a human reader only",
    ),
    (
        0x2060, 0x2060, "word joiner",
        "invisible; same hiding property as the zero-width family",
    ),
    (
        0x2061, 0x2064, "invisible math operators",
        "invisible outside a math layout engine; no use in prose or code",
    ),
    (
        0xFEFF, 0xFEFF, "zero-width no-break space (BOM)",
        "legitimate only as a byte-order mark at offset 0; hidden anywhere else",
    ),
    (
        0x202A, 0x202E, "bidi embedding/override",
        # The Trojan Source class of attack: reorder how a line renders without
        # changing the bytes a compiler or model consumes, so the reviewed text
        # and the executed text differ.
        "reorders rendered text away from source order (Trojan Source)",
    ),
    (
        0x2066, 0x2069, "bidi isolates",
        "same rendering-vs-source divergence as the override family",
    ),
    (
        0xFE00, 0xFE0F, "variation selectors",
        "invisible modifiers; can carry a payload across otherwise plain text",
    ),
    (
        0xE0100, 0xE01EF, "variation selectors supplement",
        "invisible modifiers; larger block, same property",
    ),
    (
        0x180E, 0x180E, "mongolian vowel separator",
        "zero-width in modern fonts despite not being a format character",
    ),
    (
        0x115F, 0x1160, "hangul fillers",
        "render as blank width; used to pad text invisibly",
    ),
    (
        0x3164, 0x3164, "hangul filler",
        "renders as blank width; used to pad text invisibly",
    ),
]

# Extensions worth scanning. The repo is prose plus a small amount of script;
# anything outside this set is either binary or generated.
TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".py", ".sh", ".bash", ".zsh", ".js", ".cjs",
    ".mjs", ".ts", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".ps1",
    ".html", ".css", ".sql", ".env.example",
}


def classify(codepoint: int) -> tuple[str, str] | None:
    """Return the (label, why) for a dangerous codepoint, or None if it is safe.

    Args:
        codepoint: The Unicode scalar value to test.

    Returns:
        A (label, why) pair when the codepoint falls inside a DANGEROUS range,
        otherwise None. Returning the reason alongside the label keeps the
        report self-explanatory, so a reader does not have to look the
        codepoint up to judge whether it is a real problem.
    """
    for first, last, label, why in DANGEROUS:
        if first <= codepoint <= last:
            return label, why
    return None


def is_legitimate_variation_selector(codepoint: int, prev_char: str) -> bool:
    """Return True for a variation selector doing its ordinary emoji job.

    U+FE0E and U+FE0F select text- vs emoji-presentation of the character
    immediately before them, so `⚠` + U+FE0F (rendering `⚠️`) is entirely
    normal in prose and appears throughout this repo's docs. Flagging those
    would produce a finding on nearly every heading that uses an emoji, and a
    check that cries wolf gets switched off.

    The exemption is deliberately narrow: it applies only when the preceding
    character is a symbol, which is the only position where a presentation
    selector is meaningful. A selector following a letter, a digit, or nothing
    at all is still reported.

    Args:
        codepoint: The variation-selector codepoint under test.
        prev_char: The character immediately preceding it, or "" at line start.

    Returns:
        True when this occurrence should be treated as ordinary text.
    """
    if codepoint not in (0xFE0E, 0xFE0F):
        return False
    if not prev_char:
        return False
    # 'So'/'Sk'/'Sm' cover pictographs, modifier symbols, and math symbols —
    # the bases a presentation selector legitimately attaches to.
    return unicodedata.category(prev_char) in {"So", "Sk", "Sm"}


def scan_file(path: Path) -> list[dict]:
    """Scan one file and return a finding per dangerous codepoint occurrence.

    A byte-order mark at the very start of the file is permitted, since that is
    the one position where U+FEFF carries a legitimate meaning; the same
    codepoint anywhere else is reported.

    Args:
        path: File to read. Undecodable (binary) files are skipped silently
            rather than reported, because a decode failure is not a finding.

    Returns:
        A list of findings, each with file, line, column, codepoint, character
        name, label, and why. Line and column are 1-indexed to match editors.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    # Report repo-relative when possible, absolute otherwise, so the check can
    # also be pointed at a file outside the repo (a download under review, say).
    try:
        display = str(path.relative_to(ROOT_DIR))
    except ValueError:
        display = str(path)

    findings: list[dict] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for col_no, char in enumerate(line, start=1):
            codepoint = ord(char)
            # A BOM is only legitimate as the first character of the file.
            if codepoint == 0xFEFF and line_no == 1 and col_no == 1:
                continue
            prev_char = line[col_no - 2] if col_no >= 2 else ""
            if is_legitimate_variation_selector(codepoint, prev_char):
                continue
            verdict = classify(codepoint)
            if verdict is None:
                continue
            label, why = verdict
            findings.append({
                "file": display,
                "line": line_no,
                "column": col_no,
                "codepoint": f"U+{codepoint:04X}",
                "name": unicodedata.name(char, "<unnamed>"),
                "label": label,
                "why": why,
            })
    return findings


def tracked_text_files() -> list[Path]:
    """List git-tracked files worth scanning.

    Using `git ls-files` rather than a filesystem walk means .gitignore is
    honored for free — .venv, graphify-out, and node_modules never appear —
    and it keeps the check fast enough to run on every Stop.

    Returns:
        Absolute paths to existing tracked files whose suffix is in
        TEXT_SUFFIXES. Returns an empty list outside a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT_DIR, capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    paths = []
    for name in result.stdout.decode("utf-8", "replace").split("\0"):
        if not name:
            continue
        path = ROOT_DIR / name
        if path.suffix in TEXT_SUFFIXES and path.is_file():
            paths.append(path)
    return paths


def main() -> int:
    """Scan the requested paths and print one line per finding.

    Returns:
        1 if any finding was reported, otherwise 0. The nonzero status is what
        lets a hook or CI job treat a hit as a failure without parsing output.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "paths", nargs="*", type=Path,
        help="Files to scan. Defaults to all git-tracked text files.",
    )
    args = parser.parse_args()

    targets = [p.resolve() for p in args.paths] if args.paths else tracked_text_files()

    findings: list[dict] = []
    for path in targets:
        if path.is_file():
            findings.extend(scan_file(path))

    for f in findings:
        print(
            f"{f['file']}:{f['line']}:{f['column']}: "
            f"{f['codepoint']} {f['name']} — {f['label']} ({f['why']})"
        )

    if findings:
        print(f"\n{len(findings)} invisible-Unicode finding(s) across {len(targets)} file(s).")
        return 1

    print(f"clean — no invisible Unicode in {len(targets)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
