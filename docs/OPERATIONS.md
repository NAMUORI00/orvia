# Operations

## Services and paths

- `h200-console-web.service`: administrator UI, dedicated non-login user.
- `h200-console-broker.service`: bounded host operations.
- `/etc/h200-console/web.json`: administrator hash, session secret, optional guide defaults.
- `/etc/h200-console/policy.json`: lab definitions, GPU/lab mutation allowlists, backup directory.
- `/var/lib/h200-console/audit.jsonl`: operation outcome metadata, never request bodies/passwords.
- `/var/lib/h200-console/jobs`: backup job outcomes.

```sh
systemctl status h200-console-web.service h200-console-broker.service
journalctl -u h200-console-web.service -u h200-console-broker.service --since today
```

An operator can review policy changes as root. The UI cannot grant itself access to a protected GPU. A GPU's presence in a lab is not sufficient: both allowlists must authorize the mutation.

## Backups

Each backup directory contains per-container rootfs TAR archives, a persistent-storage TAR, metadata and a SHA-256 manifest. Docker exports exclude mounted data, so the persistent-storage archive is required. Files are root-readable and may contain credentials. Never commit them to source control.

These are live best-effort backups, not memory checkpoints or transaction-consistent snapshots. Verify the SHA-256 manifest and inspect TAR listings before relying on a copy. Preserve the image/runtime configuration in metadata when planning recovery. Restore into a separately reviewed maintenance workflow; this release deliberately provides no automatic restore that would recreate or replace a container.

## Network and administrator authentication

The dashboard uses its own administrator hash; it is not PAM/LDAP/Linux-group SSO. Use an SSH tunnel or a TLS reverse proxy when transport encryption is required. Configure exact trusted hostnames via `H200_TRUSTED_HOSTS`; do not use a wildcard.

## Known limitations

- No hot GPU add/remove or base-image replacement.
- Creation uses root-approved plans. Same-configuration recreation is available only for managed read-only environments.
- Conditional internal account addition has guard tests but has not been live-tested on a writable production container.
- Account additions inside a shared container share that container's resources; they are not separate isolated environments.
- No backup retention scheduler, download endpoint or automated restore.
- No fresh-host installation validation beyond preflight on the tested server.

## Environment maintenance

The laboratory Advanced > Environment management page supports an explicitly confirmed single-user restart and same-configuration recreation. Both interrupt running work, SSH sessions, memory and temporary files. Persistent storage bindings remain unchanged. GPU/image/path migration is not performed by these controls.

Recreation pins the current image digest and preserves the inspected configuration, ports, GPU, mounts and resource limits. Writable roots, volumes outside the lab storage, multi-user containers and static IP configurations are rejected. The old container is stopped and retained with a rollback suffix; it is excluded from registration candidates. Creation or verification failure triggers rollback. Root-only records under `/var/lib/h200-console/maintenance` retain the original configuration. If the broker or host itself fails mid-operation, inspect these records; crash recovery is not automatic. Retained containers share persistent files and do not constitute backups.
