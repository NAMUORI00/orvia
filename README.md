# Orvia

**A visual control room for shared GPU research servers.**

[한국어](README.ko.md) · [Architecture](docs/ARCHITECTURE.md) · [Operations](docs/OPERATIONS.md)

Orvia maps a GPU server into laboratories, accounts and shared storage. Open a lab to inspect its accounts, adjust supported resource limits, browse official NVIDIA image tags, create live file backups, or export a one-page environment sheet in English or Korean.

## Features in 0.6

- Visual server/laboratory resource map with drill-down management.
- New laboratory provisioning and separate account containers sharing lab storage.
- Confirmed GPU reassignment, official NVIDIA image replacement and environment recreation with persistent data preservation and rollback records.
- CPU/memory limits, online storage growth for managed ext4 loop devices and live file backups.
- User/path storage accounting: allocated blocks, hidden caches, ranked paths and explicit partial results, with low-priority cached scans.
- Minute-level CPU, memory, GPU, network packet/byte and runtime metrics; seven-day retention and 2-hour/24-hour/7-day views.
- Process names and status-change events; no command arguments, packet payloads or file contents are collected by monitoring.
- English/Korean UI and access PDFs generated from registered configuration. Passwords are excluded from PDFs.

## Operational boundaries

GPU and base-image changes require confirmed environment recreation and interrupt running tasks. Memory reduction requires a restart; removing resource limits can require recreation. Persistent bindings are preserved, and writable roots are snapshotted for same-environment recreation. Other labs are not restarted. Host Docker/NVIDIA services are not restarted by these actions.

Official image updates can grant container-local sudo when selected. Researchers do not receive the host Docker socket or host administrator access. Shared-kernel containers are not virtual machines.

Live backups are not application-consistent snapshots. They include sensitive configuration and stay root-readable. Restoration remains an operator-reviewed procedure. See [observability](docs/OBSERVABILITY.md) for collection, retention and attribution limits.

## Install

Supported runtime: Linux, systemd, Docker, NVIDIA driver + NVIDIA Container Toolkit, Python 3.10–3.12 and its venv module. Ubuntu 22.04 / x86-64 was used for live verification. Other hosts require validation before enabling mutations.

```sh
sudo python3 install.py --check
sudo python3 install.py
```

The setup prompts for the administrator, listen IP, port, backup directory and GPU indexes allowed for changes. Leave the GPU list empty for monitoring-only use. It installs two dedicated services, then you register existing environments in the browser.

Source installs resolve pinned dependencies from PyPI. The downloadable package includes Linux x86-64 / CPython 3.10 wheels for offline dependency installation. No GPU workload image is downloaded automatically.

For network access, choose the server's specific internal IP. Use HTTPS via a trusted reverse proxy or an SSH tunnel on untrusted networks. The application itself serves HTTP.

## Update

```sh
sudo python3 install.py --update
```

Only Orvia services are restarted. Server-specific settings under `/etc/h200-console` are preserved. The previous application is retained under `/opt/h200-console/app.backup-*`. The installer is an interactive CLI wizard; there is no unauthenticated browser setup endpoint.

## Development

```sh
python3 -m unittest discover -s tests -v
node --check app/static/console.js
```

The control broker runs as root behind an owner-restricted Unix socket. The web process runs as a dedicated non-login account. Every live mutation checks both lab and GPU allowlists. No user-provided shell command is accepted. See [security notes](SECURITY.md) before extending control actions.

## Validation scope

Validated on one live H200 host: bilingual UI/PDFs, isolated GPU-0 account creation, official image replacement, writable-root preservation, resource-limit changes and rollback. Monitoring and storage accounting read existing research environments without changing container IDs or start times. Fresh-host installation, full-host reboot recovery and every official image tag are not claimed. See [validation](docs/VALIDATION.md).

## License

MIT. Bundled Nanum Gothic font: SIL Open Font License; see `app/fonts/OFL.txt`. Third-party Python wheels retain their upstream licenses.
