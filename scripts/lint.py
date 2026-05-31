"""
Lint the knowledge base for structural and semantic health.

Runs 7 checks: broken links, orphan pages, orphan sources, stale articles,
contradictions (LLM), missing backlinks, and sparse articles.

Usage:
    uv run python scripts/lint.py                    # all checks
    uv run python scripts/lint.py --structural-only  # skip LLM checks (faster, cheaper)
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
# Code hooks when the Agent SDK spawns a subprocess.
import os
os.environ.setdefault("CLAUDE_INVOKED_BY", "knowledge_base_lint")

import argparse
import asyncio
import re
import sys
from pathlib import Path

from config import KNOWLEDGE_DIR, REPORTS_DIR, SCRIPTS_DIR, now_iso, today_iso
from utils import (
    count_inbound_links,
    extract_wikilinks,
    file_hash,
    get_article_word_count,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_all_wiki_content,
    save_state,
    wiki_article_exists,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def check_broken_links() -> list[dict]:
    """Check for [[wikilinks]] that point to non-existent articles."""
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                continue  # daily log references are valid
            if not wiki_article_exists(link):
                issues.append({
                    "severity": "error",
                    "check": "broken_link",
                    "file": str(rel),
                    "detail": f"Broken link: [[{link}]] - target does not exist",
                })
    return issues


def check_orphan_pages() -> list[dict]:
    """Check for articles with zero inbound links."""
    issues = []
    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR)
        link_target = str(rel).replace(".md", "").replace("\\", "/")
        inbound = count_inbound_links(link_target)
        if inbound == 0:
            issues.append({
                "severity": "warning",
                "check": "orphan_page",
                "file": str(rel),
                "detail": f"Orphan page: no other articles link to [[{link_target}]]",
            })
    return issues


def check_orphan_sources() -> list[dict]:
    """Check for daily logs that haven't been compiled yet."""
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for log_path in list_raw_files():
        if log_path.name not in ingested:
            issues.append({
                "severity": "warning",
                "check": "orphan_source",
                "file": f"daily/{log_path.name}",
                "detail": f"Uncompiled daily log: {log_path.name} has not been ingested",
            })
    return issues


def check_stale_articles() -> list[dict]:
    """Check if source daily logs have changed since compilation."""
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for log_path in list_raw_files():
        rel = log_path.name
        if rel in ingested:
            stored_hash = ingested[rel].get("hash", "")
            current_hash = file_hash(log_path)
            if stored_hash != current_hash:
                issues.append({
                    "severity": "warning",
                    "check": "stale_article",
                    "file": f"daily/{rel}",
                    "detail": f"Stale: {rel} has changed since last compilation",
                })
    return issues


def check_missing_backlinks() -> list[dict]:
    """Check for asymmetric links: A links to B but B doesn't link to A."""
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        source_link = str(rel).replace(".md", "").replace("\\", "/")

        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                continue
            target_path = KNOWLEDGE_DIR / f"{link}.md"
            if target_path.exists():
                target_content = target_path.read_text(encoding="utf-8")
                if f"[[{source_link}]]" not in target_content:
                    issues.append({
                        "severity": "suggestion",
                        "check": "missing_backlink",
                        "file": str(rel),
                        "detail": f"[[{source_link}]] links to [[{link}]] but not vice versa",
                        "auto_fixable": True,
                    })
    return issues


def check_sparse_articles() -> list[dict]:
    """Check for articles with fewer than 200 words."""
    issues = []
    for article in list_wiki_articles():
        word_count = get_article_word_count(article)
        if word_count < 200:
            rel = article.relative_to(KNOWLEDGE_DIR)
            issues.append({
                "severity": "suggestion",
                "check": "sparse_article",
                "file": str(rel),
                "detail": f"Sparse article: {word_count} words (minimum recommended: 200)",
            })
    return issues


async def check_contradictions() -> list[dict]:
    """Use LLM to detect contradictions across articles."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        query,
    )

    wiki_content = read_all_wiki_content()

    prompt = f"""Review this knowledge base for contradictions, inconsistencies, or
conflicting claims across articles.

## Knowledge Base

{wiki_content}

## Instructions

Look for:
- Direct contradictions (article A says X, article B says not-X)
- Inconsistent recommendations (different articles recommend conflicting approaches)
- Outdated information that conflicts with newer entries

For each issue found, output EXACTLY one line in this format:
CONTRADICTION: [file1] vs [file2] - description of the conflict
INCONSISTENCY: [file] - description of the inconsistency

If no issues found, output exactly: NO_ISSUES

Do NOT output anything else - no preamble, no explanation, just the formatted lines."""

    response = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
    except Exception as e:
        return [{"severity": "error", "check": "contradiction", "file": "(system)", "detail": f"LLM check failed: {e}"}]

    issues = []
    if "NO_ISSUES" not in response:
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("CONTRADICTION:") or line.startswith("INCONSISTENCY:"):
                issues.append({
                    "severity": "warning",
                    "check": "contradiction",
                    "file": "(cross-article)",
                    "detail": line,
                })

    return issues


PROBE_FILE = REPORTS_DIR / "kb-probes.md"
PROBE_HEADER = "## BM25 retrieval probes"
PROBE_LINE_RE = re.compile(r'^-\s+"(?P<q>[^"]+)"\s*→\s*(?P<frag>\S.*?)\s*$')
PROBE_HIT_RATE_THRESHOLD = 0.70


def parse_probes(body: str) -> list[tuple[str, str]]:
    """Extract (query, expected_path_fragment) pairs from kb-probes.md.

    Why a strict parser: lets the probe set live alongside the human-
    readable kb_recall_hits questions in the same file without ambiguity.
    Only lines inside the `## BM25 retrieval probes` section are parsed,
    and each must match the exact `- "query" → fragment` shape.
    Fenced code blocks (```...```) inside the section are skipped so that
    the format-example block in kb-probes.md is not treated as a live probe.

    Args:
        body: Full text content of reports/kb-probes.md.

    Returns:
        List of (query, expected_fragment) tuples for each valid probe line.
    """
    in_section = False
    in_fence = False
    probes: list[tuple[str, str]] = []
    for line in body.splitlines():
        if line.startswith("## "):
            in_section = line.strip() == PROBE_HEADER
            in_fence = False
            continue
        if not in_section:
            continue
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = PROBE_LINE_RE.match(line)
        if m:
            probes.append((m.group("q"), m.group("frag")))
    return probes


def check_probe_recall() -> list[dict]:
    """Run each probe through search.py and assert expected fragment is in top-3.

    Why: this is the integration test for retrieval quality. The spec's
    phase-2 gate (add MiniLM embeddings) fires if hit-rate drops below
    70%, so we surface that signal as a lint warning, escalating to an
    error if the rate is below the gate.

    Returns:
        List of issue dicts — one `suggestion` per missed probe, plus a
        single `error` if the aggregate hit-rate falls below 70%.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    from search import search  # noqa: PLC0415  (local import after path setup)

    if not PROBE_FILE.exists():
        return [{
            "severity": "warning",
            "check": "probe_recall",
            "file": "reports/kb-probes.md",
            "detail": "Probe file missing — skipping retrieval health check",
        }]

    body = PROBE_FILE.read_text(encoding="utf-8")
    probes = parse_probes(body)
    if not probes:
        return [{
            "severity": "warning",
            "check": "probe_recall",
            "file": "reports/kb-probes.md",
            "detail": "No '## BM25 retrieval probes' section parsed",
        }]

    misses: list[tuple[str, str]] = []
    for query, expected_fragment in probes:
        hits = search(query, k=3)
        if not any(expected_fragment in h["path"] for h in hits):
            misses.append((query, expected_fragment))

    hit_rate = (len(probes) - len(misses)) / len(probes)
    issues: list[dict] = []

    for query, expected in misses:
        issues.append({
            "severity": "suggestion",
            "check": "probe_recall",
            "file": "reports/kb-probes.md",
            "detail": f'Probe miss: "{query}" → no top-3 hit contained "{expected}"',
        })

    if hit_rate < PROBE_HIT_RATE_THRESHOLD:
        issues.append({
            "severity": "error",
            "check": "probe_recall",
            "file": "reports/kb-probes.md",
            "detail": (
                f"Hit rate {hit_rate:.0%} is below the {PROBE_HIT_RATE_THRESHOLD:.0%} "
                f"phase-2 trigger — consider adding MiniLM embeddings (see "
                f"docs/superpowers/specs/2026-05-17-kb-auto-search-design.md §7)"
            ),
        })

    return issues


def generate_report(all_issues: list[dict]) -> str:
    """Generate a markdown lint report."""
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]
    suggestions = [i for i in all_issues if i["severity"] == "suggestion"]

    lines = [
        f"# Lint Report - {today_iso()}",
        "",
        f"**Total issues:** {len(all_issues)}",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        f"- Suggestions: {len(suggestions)}",
        "",
    ]

    for severity, issues, marker in [
        ("Errors", errors, "x"),
        ("Warnings", warnings, "!"),
        ("Suggestions", suggestions, "?"),
    ]:
        if issues:
            lines.append(f"## {severity}")
            lines.append("")
            for issue in issues:
                fixable = " (auto-fixable)" if issue.get("auto_fixable") else ""
                lines.append(f"- **[{marker}]** `{issue['file']}` - {issue['detail']}{fixable}")
            lines.append("")

    if not all_issues:
        lines.append("All checks passed. Knowledge base is healthy.")
        lines.append("")

    return "\n".join(lines)


def main():
    """Entry point for the lint CLI.

    Runs the six structural checks (broken links, orphan pages, orphan sources,
    stale articles, missing backlinks, sparse articles) unconditionally, then
    optionally adds the LLM contradiction check unless --structural-only is set.

    The structural checks are pure Python (no API calls) and complete in under
    a second. The contradiction check sends the full KB to the Claude API and
    costs money, so it's opt-out rather than opt-in.

    Saves the current timestamp to state.json["last_lint"] on completion, which
    lets other tools (e.g. session-start.py) report how fresh the last lint was.

    Returns:
        0 if no errors found, 1 if any error-severity issues exist.
    """
    parser = argparse.ArgumentParser(description="Lint the knowledge base")
    parser.add_argument(
        "--structural-only",
        action="store_true",
        help="Skip LLM-based checks (contradictions) - faster and free",
    )
    args = parser.parse_args()

    print("Running knowledge base lint checks...")
    all_issues: list[dict] = []

    # Structural checks (free, instant)
    checks = [
        ("Broken links", check_broken_links),
        ("Orphan pages", check_orphan_pages),
        ("Orphan sources", check_orphan_sources),
        ("Stale articles", check_stale_articles),
        ("Missing backlinks", check_missing_backlinks),
        ("Sparse articles", check_sparse_articles),
        ("Probe recall (BM25)", check_probe_recall),
    ]

    for name, check_fn in checks:
        print(f"  Checking: {name}...")
        issues = check_fn()
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")

    # LLM check (costs money)
    if not args.structural_only:
        print("  Checking: Contradictions (LLM)...")
        issues = asyncio.run(check_contradictions())
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")
    else:
        print("  Skipping: Contradictions (--structural-only)")

    # Generate and save report
    report = generate_report(all_issues)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"lint-{today_iso()}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Update state
    state = load_state()
    state["last_lint"] = now_iso()
    save_state(state)

    # Summary
    errors = sum(1 for i in all_issues if i["severity"] == "error")
    warnings = sum(1 for i in all_issues if i["severity"] == "warning")
    suggestions = sum(1 for i in all_issues if i["severity"] == "suggestion")
    print(f"\nResults: {errors} errors, {warnings} warnings, {suggestions} suggestions")

    if errors > 0:
        print("\nErrors found - knowledge base needs attention!")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
