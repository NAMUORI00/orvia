# Validation 0.5.0

Verified on a live Linux H200 host using GPU 0 test accounts only:

- Twelve boundary and UI localization tests passed; protected GPUs rejected before mutation calls.
- Korean/English page routes and environment-sheet PDFs passed.
- CPU 2 -> 2.25 -> 2 cores applied without changing container ID or start time.
- All existing production container IDs and start times remained unchanged.
- Live test-lab backup completed; archive listings and SHA-256 manifest verified.
- Installer prerequisite check passed. No fresh-host install was executed.

No production account changes, GPU resets, Docker restarts or host reboots were performed. Live account creation and backup restoration were not tested.

## 0.5.2 provisioning validation

- 19 boundary/localization tests passed on the server Python 3.10 environment.
- Browser-initiated root-approved provisioning created one isolated GPU account and a preallocated 5 TB filesystem.
- Password SSH, SFTP and a small CUDA allocation/transfer succeeded.
- Existing research container IDs and start timestamps were preserved.
- The new account was stopped and started through its recovery service; home files persisted. No host reboot was performed.
- Retiring an old test mount exposed a legacy broker Requires dependency. The unit was repaired and cleanup completed; provisioning now rejects this dependency before allocating storage.
- This is a root-prepared plan workflow, not an unrestricted browser installation wizard.

## 0.5.3 visual resource map

- Live server rack slots connect to assigned laboratories; unassigned GPUs are distinct from idle assigned GPUs.
- Browser checks covered GPU/lab selection, the unassigned GPU panel, Korean/English labels, change review and cancellation. No browser console errors were observed.
- All eight running researcher containers retained IDs and start timestamps. No researcher resource settings were changed during UI verification.
- 22 boundary/localization/metadata tests passed. Metadata editing preserves resource definitions and issues no Docker commands.
- GPU/image replacement remains disabled. Creation remains a root-prepared plan workflow. This release does not claim general lossless migration or full production lifecycle automation.

## 0.5.4 storage naming and maintenance

- 36 unit tests cover path traversal, existing storage and symlink rejection, protected labs, stale identity, downtime acknowledgement and immutable recreation payload preservation.
- An isolated GPU 0 test container on a disposable ext4 filesystem was recreated with its data intact. A deliberately failed new-container start restored the original container and preserved the same file.
- Production laboratory containers were not restarted or recreated. Full host/broker crash recovery remains untested and requires administrator inspection.
- Restart persistence passed on the same disposable environment. Browser checks covered current storage paths, Korean/English maintenance screens, and recreation confirmation cancellation; no browser errors were observed. All eight production container IDs and start timestamps remained unchanged. Disposable containers, mount, disk and units were removed.
