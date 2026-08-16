"""backup.py -- rsync-based ScholarAIO data backup."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from scholaraio import __version__
from scholaraio.core.config import BackupTargetConfig, Config

INSTANCE_BACKUP_KIND = "scholaraio-instance-backup"
INSTANCE_BACKUP_SCHEMA_VERSION = 1
INSTANCE_MANIFEST_RELATIVE_PATH = PurePosixPath(".scholaraio-control/backup-manifest.json")


class BackupConfigError(ValueError):
    """Raised when backup configuration is missing or invalid."""


@dataclass
class BackupRunResult:
    """Structured result returned from a backup invocation."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def _resolve_target(cfg: Config, target_name: str) -> BackupTargetConfig:
    target = cfg.backup.targets.get(target_name)
    if target is None:
        raise BackupConfigError(f"unknown backup target: {target_name}")
    if not target.enabled:
        raise BackupConfigError(f"backup target is disabled: {target_name}")
    if not target.host:
        raise BackupConfigError(f"backup target {target_name!r} is missing host")
    if not target.path:
        raise BackupConfigError(f"backup target {target_name!r} is missing path")
    return target


def _resolve_identity_file(cfg: Config, identity_file: str) -> str:
    if not identity_file:
        return ""
    path = Path(identity_file).expanduser()
    if not path.is_absolute():
        path = (cfg._root / path).resolve()
    return str(path)


def _build_remote_shell_parts(cfg: Config, target: BackupTargetConfig) -> list[str]:
    parts = [cfg.backup.ssh_bin]
    if target.password:
        parts.extend(
            [
                "-o",
                "PreferredAuthentications=password,keyboard-interactive",
                "-o",
                "PubkeyAuthentication=no",
            ]
        )
    else:
        # Backups should fail fast instead of hanging on interactive SSH prompts.
        parts.extend(["-o", "BatchMode=yes"])
    if target.port and target.port != 22:
        parts.extend(["-p", str(target.port)])
    identity_file = _resolve_identity_file(cfg, target.identity_file)
    if identity_file:
        parts.extend(["-i", identity_file])
    return parts


def _build_remote_shell(cfg: Config, target: BackupTargetConfig) -> str:
    return shlex.join(_build_remote_shell_parts(cfg, target))


def _build_password_env(target: BackupTargetConfig) -> tuple[dict[str, str], str] | tuple[None, None]:
    if not target.password:
        return None, None

    fd, askpass_path = tempfile.mkstemp(prefix="scholaraio-backup-askpass-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nprintf '%s\\n' \"$SCHOLARAIO_BACKUP_SSH_PASSWORD\"\n")
        os.chmod(askpass_path, 0o700)
    except Exception:
        try:
            os.unlink(askpass_path)
        except OSError:
            pass
        raise

    env = os.environ.copy()
    env.update(
        {
            "SCHOLARAIO_BACKUP_SSH_PASSWORD": target.password,
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": "scholaraio-backup",
        }
    )
    return env, askpass_path


def _destination_for(target: BackupTargetConfig) -> str:
    remote = _remote_for(target)
    return f"{remote}:{target.path.rstrip('/')}/"


def _remote_for(target: BackupTargetConfig) -> str:
    return f"{target.user}@{target.host}" if target.user else target.host


def _validate_instance_target(target: BackupTargetConfig) -> None:
    if target.scope != "instance":
        raise BackupConfigError("restore requires a backup target with scope: instance")
    if target.mode != "default":
        raise BackupConfigError("instance backups require mode: default")
    if target.exclude:
        raise BackupConfigError("instance backups cannot use exclude patterns")


def _base_rsync_command(cfg: Config, target: BackupTargetConfig, *, dry_run: bool) -> list[str]:
    cmd = [cfg.backup.rsync_bin, "-a", "--stats", "--human-readable"]
    if target.compress:
        cmd.append("-z")
    if target.mode == "append":
        cmd.append("--append")
    elif target.mode == "append-verify":
        cmd.append("--append-verify")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def _instance_relative_path(cfg: Config, path: Path) -> Path:
    root = cfg._root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise BackupConfigError(f"instance backup path must be inside {root}: {resolved}") from exc
    if relative == Path("."):
        raise BackupConfigError("instance backup cannot use the entire instance root as one component")
    return relative


def _instance_component_paths(cfg: Config) -> list[Path]:
    candidates = [
        cfg._root / "config.yaml",
        cfg._root / "config.local.yaml",
        cfg.backup_source_dir,
        cfg.workspace_dir,
        cfg.published_dir,
        cfg.control_root,
    ]
    components: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        _instance_relative_path(cfg, path)
        seen.add(resolved)
        components.append(path)
    config_path = (cfg._root / "config.yaml").resolve()
    if config_path not in seen:
        raise BackupConfigError(f"instance backup requires config.yaml under {cfg._root}")
    return components


def _relative_rsync_source(cfg: Config, path: Path) -> str:
    relative = _instance_relative_path(cfg, path).as_posix()
    suffix = "/" if path.is_dir() else ""
    return f"{str(cfg._root.resolve()).rstrip('/')}/./{relative}{suffix}"


def _write_instance_manifest(cfg: Config) -> Path:
    cfg.control_root.mkdir(parents=True, exist_ok=True)
    components = _instance_component_paths(cfg)
    payload = {
        "kind": INSTANCE_BACKUP_KIND,
        "schema_version": INSTANCE_BACKUP_SCHEMA_VERSION,
        "scholaraio_version": __version__,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "components": [
            {
                "path": _instance_relative_path(cfg, path).as_posix(),
                "type": "directory" if path.is_dir() else "file",
            }
            for path in components
        ],
    }
    manifest_path = cfg.control_root / INSTANCE_MANIFEST_RELATIVE_PATH.name
    fd, temp_path = tempfile.mkstemp(prefix="backup-manifest-", suffix=".json", dir=cfg.control_root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, manifest_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return manifest_path


def build_rsync_command(cfg: Config, target_name: str, *, dry_run: bool = False) -> list[str]:
    """Build the rsync command line for a configured backup target."""
    target = _resolve_target(cfg, target_name)
    cmd = _base_rsync_command(cfg, target, dry_run=dry_run)

    if target.scope == "instance":
        _validate_instance_target(target)
        cmd.append("--relative")
        sources = [_relative_rsync_source(cfg, path) for path in _instance_component_paths(cfg)]
    else:
        for pattern in target.exclude:
            cmd.extend(["--exclude", pattern])
        sources = [f"{cfg.backup_source_dir}/"]
    cmd.extend(["-e", _build_remote_shell(cfg, target)])
    cmd.extend(sources)
    cmd.append(_destination_for(target))
    return cmd


def _run_command(cmd: list[str], target: BackupTargetConfig) -> subprocess.CompletedProcess[str]:
    env, askpass_path = _build_password_env(target)
    run_kwargs: dict[str, Any] = {"check": False, "text": True, "capture_output": True}
    if env is not None:
        run_kwargs["env"] = env
        run_kwargs["stdin"] = subprocess.DEVNULL
    try:
        return subprocess.run(cmd, **run_kwargs)
    except OSError as exc:
        detail = exc.strerror or str(exc)
        program = Path(cmd[0]).name
        raise BackupConfigError(f"failed to execute {program} {cmd[0]!r}: {detail}") from exc
    finally:
        if askpass_path:
            try:
                os.unlink(askpass_path)
            except OSError:
                pass


def run_backup(cfg: Config, target_name: str, *, dry_run: bool = False) -> BackupRunResult:
    """Run an rsync backup for a configured target."""
    target = _resolve_target(cfg, target_name)
    if target.scope == "instance" and not dry_run:
        _validate_instance_target(target)
        _write_instance_manifest(cfg)
    cmd = build_rsync_command(cfg, target_name, dry_run=dry_run)
    completed = _run_command(cmd, target)
    return BackupRunResult(
        command=cmd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _remote_manifest_path(target: BackupTargetConfig) -> str:
    return f"{target.path.rstrip('/')}/{INSTANCE_MANIFEST_RELATIVE_PATH.as_posix()}"


def _validate_manifest(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BackupConfigError("remote backup manifest must be a JSON object")
    if payload.get("kind") != INSTANCE_BACKUP_KIND:
        raise BackupConfigError("remote target is not a ScholarAIO instance backup")
    if payload.get("schema_version") != INSTANCE_BACKUP_SCHEMA_VERSION:
        raise BackupConfigError(f"unsupported backup manifest schema: {payload.get('schema_version')!r}")
    raw_components = payload.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise BackupConfigError("remote backup manifest has no components")

    components: list[dict[str, str]] = []
    for item in raw_components:
        if not isinstance(item, dict):
            raise BackupConfigError("remote backup manifest contains an invalid component")
        path_value = item.get("path")
        type_value = item.get("type")
        if not isinstance(path_value, str) or type_value not in {"file", "directory"}:
            raise BackupConfigError("remote backup manifest contains an invalid component")
        path = PurePosixPath(path_value)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise BackupConfigError(f"unsafe path in remote backup manifest: {path_value!r}")
        components.append({"path": path.as_posix(), "type": type_value})

    validated = dict(payload)
    validated["components"] = components
    return validated


def fetch_backup_manifest(cfg: Config, target_name: str) -> dict[str, Any]:
    """Fetch and validate the manifest for a remote instance backup."""
    target = _resolve_target(cfg, target_name)
    _validate_instance_target(target)
    remote_path = shlex.quote(_remote_manifest_path(target))
    command = [
        *_build_remote_shell_parts(cfg, target),
        _remote_for(target),
        f"cat -- {remote_path}",
    ]
    completed = _run_command(command, target)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"ssh exit code {completed.returncode}"
        raise BackupConfigError(f"failed to read remote backup manifest: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BackupConfigError("remote backup manifest is not valid JSON") from exc
    return _validate_manifest(payload)


def _restore_include_patterns(manifest: Mapping[str, Any]) -> list[str]:
    patterns: list[str] = []
    seen: set[str] = set()
    for component in manifest["components"]:
        path = PurePosixPath(component["path"])
        for index in range(1, len(path.parts)):
            parent = "/" + "/".join(path.parts[:index]) + "/"
            if parent not in seen:
                seen.add(parent)
                patterns.append(parent)
        suffix = "/***" if component["type"] == "directory" else ""
        pattern = f"/{path.as_posix()}{suffix}"
        if pattern not in seen:
            seen.add(pattern)
            patterns.append(pattern)
    return patterns


def resolve_restore_destination(destination: str | Path) -> Path:
    """Resolve and minimally validate a restore destination."""
    path = Path(destination).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if path == Path(path.anchor):
        raise BackupConfigError("refusing to restore directly into a filesystem root")
    if path.exists() and not path.is_dir():
        raise BackupConfigError(f"restore destination is not a directory: {path}")
    return path


def build_restore_command(
    cfg: Config,
    target_name: str,
    destination: str | Path,
    *,
    manifest: Mapping[str, Any],
    dry_run: bool = False,
) -> list[str]:
    """Build a manifest-scoped rsync restore command."""
    target = _resolve_target(cfg, target_name)
    _validate_instance_target(target)
    validated = _validate_manifest(dict(manifest))
    restore_root = resolve_restore_destination(destination)
    cmd = _base_rsync_command(cfg, target, dry_run=dry_run)
    for pattern in _restore_include_patterns(validated):
        cmd.append(f"--include={pattern}")
    cmd.append("--exclude=*")
    cmd.extend(["-e", _build_remote_shell(cfg, target)])
    cmd.append(_destination_for(target))
    cmd.append(f"{restore_root}/")
    return cmd


def run_restore(
    cfg: Config,
    target_name: str,
    destination: str | Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    manifest: Mapping[str, Any] | None = None,
) -> BackupRunResult:
    """Restore a full instance backup into an empty or explicitly forced destination."""
    target = _resolve_target(cfg, target_name)
    _validate_instance_target(target)
    restore_root = resolve_restore_destination(destination)
    if not dry_run and not force and restore_root.exists() and any(restore_root.iterdir()):
        raise BackupConfigError(
            f"restore destination is not empty: {restore_root}; use --force to merge and overwrite matching files"
        )
    validated = _validate_manifest(dict(manifest)) if manifest is not None else fetch_backup_manifest(cfg, target_name)
    cmd = build_restore_command(
        cfg,
        target_name,
        restore_root,
        manifest=validated,
        dry_run=dry_run,
    )
    if not dry_run:
        restore_root.mkdir(parents=True, exist_ok=True)
    completed = _run_command(cmd, target)
    if completed.returncode == 0 and not dry_run:
        local_config = restore_root / "config.local.yaml"
        if local_config.exists():
            local_config.chmod(0o600)
    return BackupRunResult(
        command=cmd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
