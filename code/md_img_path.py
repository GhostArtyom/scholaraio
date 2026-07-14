"""Check image path correctness of Markdown files anywhere under ``workspace/``.

Image references are resolved as paths relative to the Markdown file's own
directory (so ``../../data/libraries/...`` climbs out of whatever project
subtree the file lives in).  Any link whose target does not exist on disk —
or that is not a relative filesystem path (http(s), data:, absolute, ...) —
is reported.

By default hidden directories (``.stversions``, ``.git`` …) are skipped; pass
``--include-hidden`` to scan them too.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Markdown: ![alt](url) — capture the url, ignoring ![] inside the alt text.
MD_IMG_RE = re.compile(r"!\[(?:[^\]\\]|\\.)*\]\(([^)]+)\)")
# HTML fallback: <img src="...">
HTML_SRC_RE = re.compile(r'<img\s+[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def iter_md_files(root: Path, include_hidden: bool = False):
    """Yield every ``*.md`` file under ``root`` (recursive).

    Files directly under ``root`` are scanned when ``root`` itself is a md file
    or when asked for a single file path.  By default any path component
    starting with ``.`` (``.stversions``, ``.git`` …) is skipped; pass
    ``include_hidden`` to scan them too.
    """
    if not root.exists():
        return
    if root.is_file():
        if root.suffix == ".md":
            yield root
        return
    for path in root.rglob("*.md"):
        if not include_hidden and any(part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def extract_image_links(text: str):
    """Yield (start_line, raw_target) for every image reference in the markdown text."""
    joined = "\n".join(text.splitlines())
    for m in MD_IMG_RE.finditer(joined):
        target = m.group(1).strip().split(" ")[0]
        line = joined[:m.start()].count("\n") + 1
        yield line, target
    for m in HTML_SRC_RE.finditer(joined):
        target = m.group(1).strip()
        line = joined[:m.start()].count("\n") + 1
        yield line, target


def find_repo_root(md_path: Path) -> Path:
    """Walk up from md_path to the first ancestor containing a ``.git`` marker.

    Falls back to the parent of the nearest ``workspace`` ancestor, and finally
    to ``/``.  Used only for best-effort resolution of absolute image paths.
    """
    for parent in md_path.parents:
        if (parent / ".git").exists():
            return parent
        if parent.name == "workspace" and parent.parent.exists():
            return parent.parent
    return md_path.parents[-1]


def _relative_to(path: str | Path, md_path: str | Path) -> str:
    """Return ``path`` expressed relative to the directory of ``md_path``.

    Unlike :meth:`Path.relative_to`, this works even when ``path`` is not a
    descendant of the markdown directory (e.g. a sibling ``data/`` tree) by
    climbing up with ``..`` components — mirroring how the image link itself
    is written in the markdown.  Falls back to the absolute path on failure.
    """
    try:
        return os.path.relpath(Path(path).resolve(), Path(md_path).resolve())
    except (ValueError, OSError):
        return str(path)


def classify(md_path: Path, target: str):
    """Return (status, resolved_or_reason). status in {ok, broken, external, fragment_only}."""
    if not target:
        return "broken", "empty image target"
    if target.startswith("#"):
        return "fragment_only", target
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target) or target.startswith(("data:", "mailto:")):
        return "external", target
    target_path = target.split("#")[0]
    if target_path.startswith("/"):
        # Absolute path — resolve from repo root as a best effort.
        resolved = (find_repo_root(md_path) / target_path.lstrip("/")).resolve()
    else:
        resolved = (md_path.parent / target_path).resolve()
    if resolved.exists():
        return "ok", str(resolved)
    return "broken", str(resolved)


def check_file(md_path: Path):
    """Return (broken, external, ok_count) for this markdown file."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    broken, external, ok_count = [], [], 0
    for line, target in extract_image_links(text):
        target_clean = target.split("#")[0]
        status, detail = classify(md_path, target_clean)
        if status == "ok":
            ok_count += 1
        elif status == "broken":
            broken.append((line, target, detail))
        else:
            external.append((line, target, status))
    return broken, external, ok_count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path("workspace"),
        help="root to scan for .md files (default: workspace)",
    )
    parser.add_argument(
        "--report-external",
        action="store_true",
        help="also list http(s)/data:/mailto:/fragment image links (skipped by default)",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="scan hidden/backup dirs (.stversions, .stfolder, .git …) too",
    )
    args = parser.parse_args(argv)

    total_files = total_broken = total_external = total_ok = 0
    has_issues = False
    current_dir: Path | None = None

    md_files = sorted(iter_md_files(args.root.resolve(), args.include_hidden))
    for md in md_files:
        total_files += 1
        broken, external, ok_count = check_file(md)
        total_ok += ok_count
        total_broken += len(broken)
        total_external += len(external)

        parent = md.parent
        if parent != current_dir:
            current_dir = parent
            print(f"\n=== {parent} ===")

        if broken:
            has_issues = True
            print(f"  ✗ {md.name}")
            for line, target, detail in broken:
                detail_rel = _relative_to(detail, md)
                print(f"    line {line}: {target}")
                print(f"    -> {detail_rel}")
        elif external and args.report_external:
            print(f"  ~ {md.name}  ({len(external)} external/fragment links)")
            for line, target, status in external:
                print(f"    line {line}: {status.upper():<13} {target}")
        elif not external:
            if ok_count:
                print(f"  ✓ {md.name}  ({ok_count} images ok)")
            else:
                print(f"  · {md.name}  (no images)")
        # else: has external links but --report-external not set → stay quiet
        if external and not args.report_external:
            print(f"  ~ {md.name}  ({len(external)} external/fragment links; use --report-external)")

    print("\n--- summary ---")
    print(f"files scanned : {total_files}")
    print(f"images ok     : {total_ok}")
    print(f"broken refs   : {total_broken}")
    print(f"external links: {total_external}" + ("" if args.report_external else " (use --report-external to show)"))

    return 1 if has_issues else 0


if __name__ == "__main__":
    sys.exit(main())
