# Backup And Restore Contract

Status: Current

Last Updated: 2026-08-16

## Purpose

ScholarAIO backup targets have two explicit scopes:

- `data` preserves the original rsync behavior for `backup.source_dir`.
- `instance` preserves the runtime-instance surfaces required for a portable restore.

The default remains `data` so existing targets do not silently change their remote layout. A target switched to `instance` should point at a dedicated empty remote directory.

## Instance Backup Layout

An instance backup preserves paths relative to the runtime-instance root:

```text
config.yaml
config.local.yaml          # when present
data/                      # or the configured backup.source_dir
workspace/                 # configured workspace root
published/                 # configured published archive root
.scholaraio-control/
  backup-manifest.json
```

Configured component roots must resolve inside the runtime-instance root. Unknown files below included directories are preserved because rsync copies whole trees. Instance targets require `mode: default` and reject exclude patterns.

The versioned manifest records the relative component paths and their file/directory types. Restore fetches and validates this manifest before copying anything. Absolute paths and traversal components are rejected, and data-only targets cannot be restored as full instances.

## Restore Safety

`backup restore` restores only manifest-listed components. It never copies arbitrary source-repository files from the remote target.

- Empty destinations are accepted by default.
- Non-empty destinations require `--force`.
- `--force` merges and overwrites matching runtime files but does not delete unrelated files.
- Filesystem roots are never valid destinations.
- Restored `config.local.yaml` is forced to owner-only (`0600`) permissions.

After relocation, path-bearing derived indexes may be stale even when the backup is complete. Users should run `scholaraio setup check` and rebuild path-sensitive indexes.

## Secret Handling

`config.local.yaml` is part of an instance backup because API keys and local target configuration are required for complete recovery. SSH encrypts it in transit and rsync preserves owner-only permissions, but the file remains plaintext at rest on the backup server. Operators must protect the remote account and storage.

Environment-only credentials are intentionally not captured. Disaster recovery on a replacement machine therefore starts with a minimal local target configuration (or SSH key) that can reach the remote backup; the restored local config then replaces that bootstrap state.

## Limitations

- Backup is an rsync mirror, not a versioned snapshot history.
- Live SQLite files may change during transfer; derived databases should be rebuilt after restore when consistency matters.
- Restore does not install ScholarAIO source code, Python dependencies, system packages, SSH host trust, or environment-variable-only secrets.
