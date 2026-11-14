"""Portable folder selection and shared content-based ignore decisions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "new-papers"
pytestmark = pytest.mark.skipif(
    any(shutil.which(command) is None for command in ("bash", "jq", "sha256sum", "find", "stat", "sort")),
    reason="PDF scan requires Bash and GNU command-line tools",
)


def select_root(candidates: list[Path], override: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("SCHOLARAIO_BRAINSTORMING_ROOT", None)
    if override is not None:
        env["SCHOLARAIO_BRAINSTORMING_ROOT"] = str(override)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; shift; select_brainstorming_root "$@"',
            "select-root",
            str(SKILL / "scripts" / "paths.sh"),
            *(str(path) for path in candidates),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize("drive", ["c", "e"])
def test_selects_the_only_existing_drive(tmp_path: Path, drive: str) -> None:
    candidates = [tmp_path / disk / "Study" / "Brainstorming" for disk in ("e", "c")]
    selected = tmp_path / drive / "Study" / "Brainstorming"
    selected.mkdir(parents=True)
    result = select_root(candidates)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(selected)


@pytest.mark.parametrize("existing_count", [0, 2])
def test_missing_or_ambiguous_drives_require_a_choice(tmp_path: Path, existing_count: int) -> None:
    candidates = [tmp_path / drive for drive in ("e", "c")]
    for directory in candidates[:existing_count]:
        directory.mkdir()
    result = select_root(candidates)
    assert result.returncode != 0
    assert not result.stdout
    assert "SCHOLARAIO_BRAINSTORMING_ROOT" in result.stderr


def test_explicit_source_resolves_ambiguity_without_falling_back(tmp_path: Path) -> None:
    candidates = [tmp_path / drive for drive in ("e", "c")]
    for directory in candidates:
        directory.mkdir()
    result = select_root(candidates, override=candidates[1])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(candidates[1])
    missing = select_root(candidates, override=tmp_path / "missing")
    assert missing.returncode != 0
    assert not missing.stdout


@pytest.mark.parametrize("drive", ["c", "e"])
def test_scan_shares_ignores_and_keeps_reports_local(tmp_path: Path, drive: str) -> None:
    repo = tmp_path / "repo"
    skill = repo / ".claude" / "skills" / "new-papers"
    shutil.copytree(SKILL / "scripts", skill / "scripts")
    source = tmp_path / "mnt" / drive / "Study" / "Brainstorming"
    directories = [
        source / name for name in ("Error Correction", "Architecture/3.Trapped-Ion", "Architecture/4.Neutral-Atom")
    ]
    for directory in directories:
        directory.mkdir(parents=True)
    (directories[0] / "new.PDF").write_bytes(b"new candidate")
    (directories[1] / "renamed.pdf").write_bytes(b"new candidate")
    (directories[0] / "old.pdf").write_bytes(b"ignored content")
    (directories[2] / "known.pdf").write_bytes(b"library content")
    library = repo / "data" / "libraries" / "papers"
    library.mkdir(parents=True)
    (library / "known.pdf").write_bytes(b"library content")
    ignored = json.dumps([hashlib.sha256(b"ignored content").hexdigest()])
    (skill / "ignored.json").write_text(ignored, encoding="utf-8")
    env = {**os.environ, "SCHOLARAIO_BRAINSTORMING_ROOT": str(source)}
    command = ["bash", str(skill / "scripts" / "scan.sh")]

    for first_scan in (True, False):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        report = json.loads((skill / "state" / "report.json").read_text(encoding="utf-8"))
        assert report["first_scan"] is first_scan
        assert report["source_pdf_count"] == 4
        assert report["unique_pdf_count"] == 3
        assert len(report["candidates"]) == 1
        assert len(report["candidates"][0]["paths"]) == 2
        assert report["candidates"][0]["new_since_last_scan"] is first_scan
        assert sum(file["ignored"] for file in report["files"]) == 1
        assert all(not path["relative_path"].startswith("/") for path in report["candidates"][0]["paths"])
    markdown = (skill / "state" / "candidates.md").read_text(encoding="utf-8")
    assert report["candidates"][0]["paths"][0]["relative_path"] in markdown
    assert str(source) not in markdown
    assert (skill / "ignored.json").read_text(encoding="utf-8") == ignored
    assert not (skill / "state" / "ignored.json").exists()
    assert not (repo / "workspace").exists()

    (skill / "state" / "report.json").write_text("preserve previous scan", encoding="utf-8")
    (directories[2] / "known.pdf").unlink()
    directories[2].rmdir()
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert (skill / "state" / "report.json").read_text(encoding="utf-8") == "preserve previous scan"
