"""Tests for rsync backup configuration, command planning, and execution."""

from __future__ import annotations

import json
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio.core.config import _build_config
from scholaraio.interfaces.cli import compat as cli


def _build_backup_cfg(tmp_path: Path):
    return _build_config(
        {
            "backup": {
                "source_dir": "data",
                "targets": {
                    "lab": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio",
                        "port": 2222,
                        "identity_file": "secrets/id_ed25519",
                        "mode": "append-verify",
                        "compress": True,
                        "enabled": True,
                        "exclude": ["*.tmp", "metrics.db"],
                    }
                },
            }
        },
        tmp_path,
    )


def _build_instance_cfg(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("backup: {}\n", encoding="utf-8")
    local_config = tmp_path / "config.local.yaml"
    local_config.write_text('llm:\n  api_key: "secret"\n', encoding="utf-8")
    local_config.chmod(0o600)
    (tmp_path / "data" / "libraries" / "papers").mkdir(parents=True)
    (tmp_path / "workspace" / "review").mkdir(parents=True)
    (tmp_path / "published").mkdir()
    return _build_config(
        {
            "backup": {
                "targets": {
                    "instance": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio-instance",
                        "port": 2222,
                        "scope": "instance",
                    }
                }
            }
        },
        tmp_path,
    )


def _instance_manifest() -> dict[str, object]:
    return {
        "kind": "scholaraio-instance-backup",
        "schema_version": 1,
        "scholaraio_version": "2.0.0",
        "components": [
            {"path": "config.yaml", "type": "file"},
            {"path": "config.local.yaml", "type": "file"},
            {"path": "data", "type": "directory"},
            {"path": "workspace", "type": "directory"},
            {"path": ".scholaraio-control", "type": "directory"},
        ],
    }


def test_build_rsync_command_uses_configured_target_and_flags(tmp_path: Path):
    from scholaraio.services.backup import build_rsync_command

    cfg = _build_backup_cfg(tmp_path)

    cmd = build_rsync_command(cfg, "lab", dry_run=True)

    assert cmd[0] == "rsync"
    assert "-a" in cmd
    assert "-z" in cmd
    assert "--append-verify" in cmd
    assert "--dry-run" in cmd
    assert "--exclude" in cmd
    assert cmd[-1] == "alice@backup.example.com:/srv/scholaraio/"
    assert cmd[-2] == f"{(tmp_path / 'data').resolve()}/"
    assert "-e" in cmd
    ssh_cmd = cmd[cmd.index("-e") + 1]
    assert "ssh" in ssh_cmd
    assert "-p 2222" in ssh_cmd
    assert "-o BatchMode=yes" in ssh_cmd
    assert f"-i {(tmp_path / 'secrets' / 'id_ed25519').resolve()}" in ssh_cmd


def test_build_rsync_command_rejects_missing_target(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_rsync_command

    cfg = _build_backup_cfg(tmp_path)

    with pytest.raises(BackupConfigError, match="unknown backup target"):
        build_rsync_command(cfg, "missing")


def test_build_rsync_command_rejects_disabled_target(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_rsync_command

    cfg = _build_config(
        {
            "backup": {
                "targets": {
                    "archive": {
                        "host": "backup.example.com",
                        "path": "/srv/archive",
                        "enabled": False,
                    }
                }
            }
        },
        tmp_path,
    )

    with pytest.raises(BackupConfigError, match="disabled"):
        build_rsync_command(cfg, "archive")


def test_build_rsync_command_switches_to_password_auth_when_password_is_configured(tmp_path: Path):
    from scholaraio.services.backup import build_rsync_command

    cfg = _build_config(
        {
            "backup": {
                "targets": {
                    "lab": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio",
                        "port": 2222,
                        "password": "secret",
                    }
                }
            }
        },
        tmp_path,
    )

    cmd = build_rsync_command(cfg, "lab", dry_run=True)
    ssh_cmd = cmd[cmd.index("-e") + 1]

    assert "-o BatchMode=yes" not in ssh_cmd
    assert "-o PreferredAuthentications=password,keyboard-interactive" in ssh_cmd
    assert "-o PubkeyAuthentication=no" in ssh_cmd


def test_build_instance_rsync_command_preserves_runtime_layout(tmp_path: Path):
    from scholaraio.services.backup import build_rsync_command

    cfg = _build_instance_cfg(tmp_path)

    cmd = build_rsync_command(cfg, "instance", dry_run=True)

    assert "--relative" in cmd
    assert "--delete" in cmd
    assert "--dry-run" in cmd
    assert f"{tmp_path.resolve()}/./config.yaml" in cmd
    assert f"{tmp_path.resolve()}/./config.local.yaml" in cmd
    assert f"{tmp_path.resolve()}/./data/" in cmd
    assert f"{tmp_path.resolve()}/./workspace/" in cmd
    assert f"{tmp_path.resolve()}/./published/" in cmd
    assert cmd[-1] == "alice@backup.example.com:/srv/scholaraio-instance/"
    assert cmd.index("-e") < cmd.index(f"{tmp_path.resolve()}/./data/")


def test_instance_backup_rejects_append_modes_and_excludes(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_rsync_command

    cfg = _build_instance_cfg(tmp_path)
    cfg.backup.targets["instance"].mode = "append"
    with pytest.raises(BackupConfigError, match="mode: default"):
        build_rsync_command(cfg, "instance")

    cfg.backup.targets["instance"].mode = "default"
    cfg.backup.targets["instance"].exclude = ["*.tmp"]
    with pytest.raises(BackupConfigError, match="cannot use exclude"):
        build_rsync_command(cfg, "instance")


def test_run_backup_invokes_subprocess_with_planned_command(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import run_backup

    cfg = _build_backup_cfg(tmp_path)
    seen: list[list[str]] = []

    def fake_run(cmd, check, text, **kwargs):
        seen.append(cmd)
        assert check is False
        assert text is True
        assert kwargs.get("capture_output") is True
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    result = run_backup(cfg, "lab", dry_run=False)

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert seen


def test_run_backup_reports_missing_rsync_binary_as_config_error(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import BackupConfigError, run_backup

    cfg = _build_backup_cfg(tmp_path)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("rsync not found")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    with pytest.raises(BackupConfigError, match="failed to execute rsync"):
        run_backup(cfg, "lab", dry_run=False)


def test_run_backup_uses_askpass_env_for_password_targets(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import run_backup

    cfg = _build_config(
        {
            "backup": {
                "targets": {
                    "lab": {
                        "host": "backup.example.com",
                        "user": "alice",
                        "path": "/srv/scholaraio",
                        "password": "secret",
                    }
                }
            }
        },
        tmp_path,
    )
    seen: dict[str, object] = {}

    def fake_run(cmd, check, text, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        assert kwargs.get("stdin") is subprocess.DEVNULL
        env = kwargs.get("env") or {}
        assert env["SCHOLARAIO_BACKUP_SSH_PASSWORD"] == "secret"
        assert env["SSH_ASKPASS_REQUIRE"] == "force"
        assert env["DISPLAY"] == "scholaraio-backup"
        assert "SSH_ASKPASS" in env
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    result = run_backup(cfg, "lab", dry_run=False)

    assert result.returncode == 0
    assert result.stdout == "ok"


def test_run_instance_backup_writes_versioned_manifest(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import run_backup

    cfg = _build_instance_cfg(tmp_path)

    def fake_run(cmd, check, text, **kwargs):
        assert check is False
        assert text is True
        manifest_path = tmp_path / ".scholaraio-control" / "backup-manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["kind"] == "scholaraio-instance-backup"
        assert payload["schema_version"] == 1
        assert {item["path"] for item in payload["components"]} >= {
            "config.yaml",
            "config.local.yaml",
            "data",
            "workspace",
            "published",
            ".scholaraio-control",
        }
        assert f"{tmp_path.resolve()}/./.scholaraio-control/" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    result = run_backup(cfg, "instance")

    assert result.returncode == 0
    assert (tmp_path / ".scholaraio-control" / "backup-manifest.json").stat().st_mode & 0o777 == 0o600


def test_fetch_backup_manifest_uses_ssh_and_validates_payload(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import fetch_backup_manifest

    cfg = _build_instance_cfg(tmp_path)
    seen: list[str] = []

    def fake_run(cmd, check, text, **kwargs):
        seen.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_instance_manifest()), stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    manifest = fetch_backup_manifest(cfg, "instance")

    assert manifest["schema_version"] == 1
    assert "alice@backup.example.com" in seen
    assert any("backup-manifest.json" in item for item in seen)


def test_build_restore_command_limits_transfer_to_manifest_components(tmp_path: Path):
    from scholaraio.services.backup import build_restore_command

    cfg = _build_instance_cfg(tmp_path)
    destination = tmp_path / "restored"

    cmd = build_restore_command(
        cfg,
        "instance",
        destination,
        manifest=_instance_manifest(),
        dry_run=True,
    )

    assert "--include=/config.yaml" in cmd
    assert "--include=/config.local.yaml" in cmd
    assert "--include=/data/***" in cmd
    assert "--include=/workspace/***" in cmd
    assert "--include=/.scholaraio-control/***" in cmd
    assert "--exclude=*" in cmd
    assert cmd[-2] == "alice@backup.example.com:/srv/scholaraio-instance/"
    assert cmd[-1] == f"{destination.resolve()}/"


def test_restore_rejects_data_only_targets(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_restore_command

    cfg = _build_backup_cfg(tmp_path)

    with pytest.raises(BackupConfigError, match="scope: instance"):
        build_restore_command(cfg, "lab", tmp_path / "restore", manifest=_instance_manifest())


def test_restore_rejects_nonempty_destination_without_force(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, run_restore

    cfg = _build_instance_cfg(tmp_path)
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "config.yaml").write_text("existing: true\n", encoding="utf-8")

    with pytest.raises(BackupConfigError, match="not empty"):
        run_restore(cfg, "instance", destination, manifest=_instance_manifest())


def test_restore_rejects_manifest_path_traversal(tmp_path: Path):
    from scholaraio.services.backup import BackupConfigError, build_restore_command

    cfg = _build_instance_cfg(tmp_path)
    manifest = _instance_manifest()
    manifest["components"] = [{"path": "../config.local.yaml", "type": "file"}]

    with pytest.raises(BackupConfigError, match="unsafe path"):
        build_restore_command(cfg, "instance", tmp_path / "restore", manifest=manifest)


def test_restore_sets_local_config_permissions_to_owner_only(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import run_restore

    cfg = _build_instance_cfg(tmp_path)
    destination = tmp_path / "restore"

    def fake_run(cmd, check, text, **kwargs):
        destination.mkdir(parents=True, exist_ok=True)
        restored_config = destination / "config.local.yaml"
        restored_config.write_text("llm:\n  api_key: restored\n", encoding="utf-8")
        restored_config.chmod(0o644)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("scholaraio.services.backup.subprocess.run", fake_run)

    result = run_restore(cfg, "instance", destination, manifest=_instance_manifest())

    assert result.returncode == 0
    assert (destination / "config.local.yaml").stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is required")
def test_instance_backup_and_manifest_scoped_restore_round_trip(tmp_path: Path):
    from scholaraio.services.backup import (
        _write_instance_manifest,
        build_restore_command,
        build_rsync_command,
    )

    instance_root = tmp_path / "instance"
    instance_root.mkdir()
    cfg = _build_instance_cfg(instance_root)
    paper = instance_root / "data" / "libraries" / "papers" / "paper-1"
    paper.mkdir()
    (paper / "paper.pdf").write_bytes(b"pdf")
    paper_markdown = paper / "paper.md"
    paper_markdown.write_text("paper", encoding="utf-8")
    (paper / "meta.json").write_text('{"title": "Paper"}\n', encoding="utf-8")
    (instance_root / "workspace" / "review" / "notes.md").write_text("notes", encoding="utf-8")
    _write_instance_manifest(cfg)

    remote_root = tmp_path / "remote"
    backup_cmd = build_rsync_command(cfg, "instance")
    shell_index = backup_cmd.index("-e")
    local_backup_cmd = [
        *backup_cmd[:shell_index],
        *backup_cmd[shell_index + 2 : -1],
        f"{remote_root}/",
    ]
    subprocess.run(local_backup_cmd, check=True, capture_output=True, text=True)

    paper_markdown.unlink()
    subprocess.run(local_backup_cmd, check=True, capture_output=True, text=True)
    assert not (remote_root / "data" / "libraries" / "papers" / "paper-1" / "paper.md").exists()

    (remote_root / "unrelated.txt").write_text("ignore", encoding="utf-8")

    manifest = json.loads((remote_root / ".scholaraio-control" / "backup-manifest.json").read_text(encoding="utf-8"))
    restore_root = tmp_path / "restored"
    restore_cmd = build_restore_command(cfg, "instance", restore_root, manifest=manifest)
    shell_index = restore_cmd.index("-e")
    local_restore_cmd = [
        *restore_cmd[:shell_index],
        f"{remote_root}/",
        restore_cmd[-1],
    ]
    subprocess.run(local_restore_cmd, check=True, capture_output=True, text=True)

    assert (restore_root / "config.yaml").exists()
    assert (restore_root / "config.local.yaml").exists()
    assert (restore_root / "data" / "libraries" / "papers" / "paper-1" / "paper.pdf").read_bytes() == b"pdf"
    assert not (restore_root / "data" / "libraries" / "papers" / "paper-1" / "paper.md").exists()
    assert (restore_root / "workspace" / "review" / "notes.md").read_text(encoding="utf-8") == "notes"
    assert not (restore_root / "unrelated.txt").exists()


def test_cmd_backup_list_displays_configured_targets(tmp_path: Path, monkeypatch):
    cfg = _build_backup_cfg(tmp_path)
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))

    cli.cmd_backup(Namespace(backup_action="list"), cfg)

    assert any("Backup source directory" in msg for msg in messages)
    assert any("[lab] enabled" in msg for msg in messages)
    assert any("Scope: data" in msg for msg in messages)
    assert any("append-verify" in msg for msg in messages)


def test_cmd_backup_restore_reports_dry_run_completion(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.fetch_backup_manifest",
        lambda *_args, **_kwargs: _instance_manifest(),
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.build_restore_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "alice@host:/src/", "/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_restore",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    cli.cmd_backup(
        Namespace(
            backup_action="restore",
            target="instance",
            destination=str(tmp_path / "restore"),
            dry_run=True,
            force=False,
        ),
        _build_instance_cfg(tmp_path),
    )

    assert any("About to run restore command" in msg for msg in messages)
    assert any("Restore dry run complete" in msg for msg in messages)


def test_cmd_backup_run_reports_dry_run_completion(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=True), _build_backup_cfg(tmp_path))

    assert any("About to run backup command" in msg for msg in messages)
    assert any("Dry run complete" in msg for msg in messages)


def test_cmd_backup_run_displays_shell_quoted_preview(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: [
            "rsync",
            "-a",
            "-e",
            "ssh -p 2222 -i /tmp/test key",
            "/src/",
            "alice@host:/dst/",
        ],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=True), _build_backup_cfg(tmp_path))

    assert any("About to run backup command" in msg for msg in messages)
    assert any("'ssh -p 2222 -i /tmp/test key'" in msg for msg in messages)


def test_cmd_backup_run_exits_cleanly_when_backup_runtime_error_occurs(tmp_path: Path, monkeypatch):
    from scholaraio.services.backup import BackupConfigError

    messages: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["missing-rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BackupConfigError("failed to execute rsync")),
    )

    with pytest.raises(SystemExit, match="1"):
        cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=False), _build_backup_cfg(tmp_path))

    assert any("About to run backup command" in msg for msg in messages)
    assert any("failed to execute rsync" in msg for msg in errors)


def test_cmd_backup_run_shows_guidance_for_noninteractive_auth_failures(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=255,
            stdout="",
            stderr="alice@host: Permission denied (publickey,password).",
        ),
    )

    with pytest.raises(SystemExit, match="255"):
        cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=False), _build_backup_cfg(tmp_path))

    assert any("Permission denied" in msg for msg in messages)
    assert any("BatchMode=yes" in msg for msg in messages)
    assert any("config.local.yaml" in msg for msg in messages)
    assert any("known_hosts" in msg for msg in messages)
    assert any("Backup failed, exit code: 255" in msg for msg in errors)


def test_cmd_backup_run_shows_guidance_for_host_key_failures(tmp_path: Path, monkeypatch):
    messages: list[str] = []
    errors: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr(cli._log, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(
        "scholaraio.services.backup.build_rsync_command",
        lambda *_args, **_kwargs: ["rsync", "-a", "/src/", "alice@host:/dst/"],
    )
    monkeypatch.setattr(
        "scholaraio.services.backup.run_backup",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=255,
            stdout="",
            stderr="Host key verification failed.",
        ),
    )

    with pytest.raises(SystemExit, match="255"):
        cli.cmd_backup(Namespace(backup_action="run", target="lab", dry_run=False), _build_backup_cfg(tmp_path))

    assert any("Host key verification failed" in msg for msg in messages)
    assert any("known_hosts" in msg for msg in messages)
    assert any("ssh-keyscan" in msg for msg in messages)
    assert any("Backup failed, exit code: 255" in msg for msg in errors)
