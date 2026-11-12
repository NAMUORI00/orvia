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
