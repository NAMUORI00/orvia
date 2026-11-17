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

## 0.5.5 administration and visual resource map

- Automated tests cover file traversal/symlink/hardlink rejection, account metadata, versioned guide generation without passwords, official image references, GPU configuration payloads, stale-state and downtime confirmations.
- Live mutation verification is restricted to temporary GPU 0 containers and a 64 MiB ext4 test mount. Production laboratory container IDs and start timestamps are compared before and after.
- Verified account creation, official CUDA image replacement, home-data persistence, writable-root snapshot recreation, restart recovery and rollback on an injected second-container start failure.
- GPU payload mapping is unit-tested for multiple GPUs; live reassignment testing retains GPU 0 only. No production laboratory GPU is reassigned for validation.
- Korean/English PDFs are rendered and inspected. No full-host reboot, crash-during-transaction recovery, every provider image tag, or clean-host installation is claimed.

## 0.6.0 Orvia monitoring and storage analysis

- Read-only verification of registered account metadata, CPU/memory/block-I/O statistics, network byte/packet counters, process names and eight GPU sensors. No container restart or GPU workload probe is required.
- Storage tests verify hidden-cache inclusion, symlink exclusion, hard-link deduplication, sparse-file block accounting and explicit partial results. Telemetry tests verify interface counter parsing and edge-triggered event records.
- Hardware/traffic rates are recorded from deployment onward. Seven-day retention and historical-window queries are configured; seven elapsed days of operation have not been observed at release.
- Existing account container IDs and start timestamps are compared before and after deployment.

## 0.6.1 overview-first interaction

- Operational overview uses four resource trend charts and account activity tiles. Numerical readings appear on pointer hover, touch or keyboard focus; account selection opens details.
- Storage overview shows capacity and account shares before revealing a selected account's paths. Hardware, events and measurement notes remain available through explicit actions.
- Browser verification covered keyboard chart readings, account details and storage path drill-down against live read-only metrics. Collection intervals and retention are unchanged.
- The 65 Linux unit tests passed. Existing research containers are preserved during dashboard-only deployment.

## 0.6.2 account network usage

- Ranked received/sent volume uses raw counter deltas before chart downsampling. Container identity changes, counter resets and gaps over three minutes are excluded; measured duration remains explicit.
- Account selection opens received/sent charts, period totals, sampled peak rate/time and up to 20 recent packet error/drop intervals. No packet payload or destination collection was added.
- Tests cover restart/reset/gap boundaries, lab-scoped account identity and packet error deltas. Deployment only restarts dashboard services.

## 0.6.3 configurable history

- Added local-date range queries (maximum 31 days), empty-period clearing, and historical views without automatic polling. Events are filtered to the selected interval.
- Default retention: 7 days of minute detail and 90 days of 15-minute summaries; selectable detail 1/3/7 days and total retention 30/60/90/180 days. Authenticated CSRF-protected settings include automatic-deletion acknowledgement.
- At most four closed buckets are archived per collection cycle. Unarchived samples are protected from pruning; a predecessor is retained for counter boundaries. SQLite freed pages are reused without full VACUUM.
- 71 Linux tests passed, including bounded backfill, expiry, average/max preservation, archive/raw network totals, date filtering and settings bounds. Browser verification covered empty dates and saving default retention.
- Current small-dataset read measurements were 0.8–4.7 ms with approximately 19 MiB peak RSS for the standalone read process. These are not a 90-day production benchmark. Existing research containers are unchanged by dashboard deployment.

## 0.6.4 laboratory hierarchy, permission profiles and visual management

- Monitoring separates whole-server trends, laboratory resource cards and the selected laboratory's accounts. CPU/memory account totals remain distinct from host-wide utilization. GPU utilization and VRAM remain shared laboratory metrics; per-account GPU usage is explicitly uncollected. Historical samples without allocation metadata remain N/A.
- Access-sheet laboratory selection uses visual cards. Permission text derives from structured policy and container isolation flags rather than saved prose. Writable root filesystems no longer imply sudo. Profile changes use the existing environment replacement workflow and its downtime/recreation confirmations; this release does not introduce live sudo toggling.
- Versioned JSON profiles offer standard user and container administrator roles, both without host Docker delegation. New accounts in a container-admin laboratory receive their own sudo rule. Tests validate policy selection, conflicting runtime constraints, inheritance directives and document text; production researcher permissions are not changed during testing.
- Activity cards distinguish accepted asynchronous requests from job outcomes. Read-only events are folded separately, action identifiers remain available, and the audit tail is bounded to 256 KiB / 100 events.
- Browser checks cover laboratory/account selection, access-sheet cards, permission preset presentation and activity records. Template syntax is checked alongside the Python suite after a template formatting defect was found and repaired.

- Final verification: 78 Linux tests passed; Korean and English access-sheet PDF generation succeeded using live configured data. No production permission changes, new researcher containers or environment replacement were executed.

## 0.6.5 official image selection and creation wizard

- Creation separates laboratory/image, resource allocation and first account. GPU cards support click, keyboard and drag/drop; storage uses presets, slider and numeric input.
- Official NVIDIA CUDA and NGC PyTorch catalogs are the default. Locally available official layer prefixes identify the bases used by existing laboratories; all four current image families matched nvidia/cuda:12.4.1-base-ubuntu22.04. Customized laboratory image reuse is collapsed under advanced controls.
- Official creation validates the provider reference, pins an available image ID, and adds SSH/Python tools. Conda and additional libraries are not implied by a CUDA base. Live image catalog and wizard selection were checked; 80 Linux unit tests passed. Full creation from a new official base was not executed.
- Deployment restarts dashboard services only; existing researcher containers are protected.

## 0.6.7 official-image end-to-end verification and visual configuration

- A disposable laboratory was provisioned through authenticated HTTP creation and apply endpoints from nvidia/cuda:12.4.1-base-ubuntu22.04, using GPU 0 only and a 2 GB dedicated filesystem. UI checks covered provider/version selection and a live image/GPU/storage/account configuration diagram.
- The first SSH test found research.sh copied as root-only under the service umask. The image recipe now explicitly sets mode 644. The disposable laboratory was removed and generated again; real password SSH then completed without profile errors.
- The account saw exactly GPU 0's UUID. CUDA driver initialization, a 4 MiB device allocation, memset, synchronization and release passed. Python 3.10.12 was available. This does not validate PyTorch or every upstream image tag.
- Allocating a 3 GiB file on the 2 GB test filesystem failed as expected. After restarting only the test container, the persisted file and password SSH remained usable. Read-only system paths and absence of Docker socket were checked.
- Existing eight researcher container IDs, start times, running states and HostConfig were compared before/after. Test resources were isolated from existing laboratory storage.
- The configuration preview labels settings as not yet created, highlights changed cards briefly, respects reduced motion, and uses no external model or rendering dependency.

## 0.6.8 existing laboratory configuration comparison

- Existing laboratory overview, GPU and storage pages share a current configuration diagram based on existing read-only status/catalog data. GPU and storage edit forms show a separate proposed configuration with added/removed GPU chips and capacity differences. Allocated disk capacity is used consistently on both sides, rather than mixing it with filesystem usable capacity.
- Preview code has no fetch, submit or server mutation. Existing confirmation and acknowledgement forms remain authoritative. Invalid values, empty GPU selection and reset are handled locally.
- Browser checks on graphics exercised GPU 0 selection without applying it, reset, and a 1000-to-1500 GB storage preview (+500 GB). No production mutation was submitted.

## 0.6.9 per-user CPU and memory limit comparison

- CPU/memory management displays each laboratory account with before/proposed limits. Bars show the fraction of host capacity represented by each limit, not reserved capacity or measured use. Unlimited settings use a striped bar and explicit label.
- Only the selected account reflects unsaved form values. Changing the selected account restores its configured limits. Input reset, invalid input and restart/recreation impact are handled locally; no requests are sent by the preview script.
- Browser checks exercised a 16-core/128-GiB preview and switching accounts without submitting the form. Existing execution and allocation were not modified.

## 0.6.10 actual laboratory and account usage

- Laboratory overview and CPU/memory pages prioritize actual usage. Allocation controls are folded separately. Account CPU is Docker CPU percentage divided by logical CPU count; memory uses Docker reported bytes divided by host memory. Absolute core-equivalent and GiB values accompany percentages. Laboratory totals sum the configured account containers, not host-wide utilization.
- A single latest SQLite row supplies each view; the endpoint strips process and unrelated account fields. No additional Docker stats/process sampling occurs on page requests. Refresh is once per minute and stops when hidden. Missing/stale samples show N/A instead of invented zeros.
- Read-only browser validation used running graphics accounts; no allocation, restart or researcher container mutation was submitted.


## 0.7.0 shared laboratory accounts and account management

- New laboratories mount persistent home and account databases into one shared container. Legacy laboratories are not automatically migrated.
- The existing Byun lab was converted through the dashboard after two GPU-idle checks. Its image, host key, Hasnain credential record and home path were retained.
- Ten additional accounts were created through the dashboard. All eleven accounts passed real password SSH authentication on the lab port and detected both assigned GPUs, Python and Conda. No workloads were launched.
- Other laboratories' seven container IDs and start timestamps remained unchanged. The shared container was not restarted during account creation or UI deployment.
- Account cards expose details, metadata, password changes, backup and deletion progressively. Restart is a single lab-level control; GPU activity blocks it.
- Account backups were exercised through the live UI without deleting the account. Deletion was tested on temporary fixture files: the home archive remained readable, the target account was removed, and the peer data/credential record was unchanged. Live research accounts were not deleted or password-reset for testing.
- Shared-container counters are reported once at lab level; unavailable per-user network/CPU attribution is not fabricated.
- 96 automated tests passed, including bound-file inode preservation, password target isolation, GPU activity gates, and backup/delete safeguards.
- Bound account files survive stop/start by design; no additional production restart was performed solely for persistence testing.


## 0.7.1 per-user environments within a laboratory

- New laboratories default to separate account containers and SSH ports. Personal homes and a common `/shared` directory use the laboratory's single storage allocation.
- Account creation respects the existing laboratory layout. Existing shared-container laboratories remain supported until explicitly migrated.
- The dashboard migration checks the expected container state, GPU activity, user processes, and read-only system image. It preserves UID, password hashes, personal home paths, and the original image. The previous container remains stopped for recovery.
- On 2026-11-16 the Byun laboratory was migrated through the dashboard: 11 containers, 11 distinct SSH ports, GPUs 3 and 4, and unchanged 5 TB storage allocation. All 11 actual SSH logins succeeded. Python 3.10.22 and Conda 26.7.2 remained available. Personal-home isolation, common-folder access, Docker socket denial, and protected password files were verified.
- Seven containers belonging to other laboratories retained their IDs and start timestamps. No GPU workload was launched and no research container reboot test was performed.
- CPU and memory remain unrestricted for this laboratory. Per-container limits are not an aggregate laboratory cgroup quota.
- The retained rollback container and credential/configuration backups are intentional recovery assets. Newly created laboratory provisioning was covered by automated tests, not another live research-lab creation in this change.

- Automated validation: 101 unit tests passed; Korean and English account views verified in the browser after deployment.


## 0.7.2 shared-container consolidation

- Environment management provides an explicit per-laboratory shared-container conversion with a selected common SSH port. It checks current container identity, GPU activity, user/extra root processes, private home permissions, identical immutable images, compatible resource/security settings, environment variables, mounts, and account database conflicts.
- Compatible laboratories can be converted after notifying members. Different system images or resource policies are deliberately rejected until aligned; this is not a package-merging mechanism. New-laboratory defaults are unchanged.
- The worker merges account records without changing password hashes or UIDs, keeps personal home paths and common data, retains stopped originals, updates only the selected laboratory, and registers mount-first recovery for the shared container. Failed operations attempt to restore prior containers and configuration.
- 2026-11-17: Byun laboratory converted through the dashboard. All 11 existing accounts passed actual SSH password login on port 2208. Python 3.10.22, Conda 26.7.2, GPUs 3 and 4, writable home/common directories, peer-home permission denial, protected account databases, protected admin directory, and absence of Docker socket were verified.
- Password hashes, UID ownership, and home modes were compared with pre-conversion settings. Other laboratories' seven containers retained their IDs and start timestamps. They were not restarted or modified. Stopped Byun originals remain for recovery.
- 106 unit tests passed, including credential preservation, account conflicts, duplicate UID rejection, and missing-password rejection. No destructive account-management test, GPU workload, or server reboot was performed on production.


## 0.7.3 native password changes with persistent account data

- Optional `account_backend: native_etc` uses a writable, administrator-owned persistent `/etc` directory. Dashboard password changes call native `chpasswd -e` over stdin, preserving native password locking and avoiding stale whole-file writes. Native account creation/deletion use shadow tools; other laboratories retain their original backend.
- On 2026-11-17 only Byun was migrated. The existing writable system layer was committed while stopped, configuration files copied with symlinks preserved, account hashes/UIDs and home paths retained, and mount-first recovery updated. A first Docker copy attempt rejected a relative symlink and rolled back to the original container; the subsequent archive extraction created symlinks last and completed.
- Two temporary accounts were created via the actual authenticated dashboard HTTP routes. Native `passwd` and dashboard changes ran concurrently for separate accounts; new passwords authenticated and old passwords were rejected. A subsequent dashboard update to an internally changed account and `ywkim` sudo passwd both succeeded. A standard user could not change another user's password. Container ID/start time remained unchanged during password tests.
- Dashboard backup/deletion removed both temporary accounts; their test homes and test backup artifacts were cleaned. All twelve existing accounts still authenticated using unchanged passwords. Stored original password hashes were compared and remained identical. Other research containers retained IDs/start times.
- 109 unit tests passed. No post-change reboot persistence test was performed; persistence was verified by the shared host mount and observed account-file updates.
- Data storage remains a 5,000,000,000,000-byte allocation (filesystem about 4.96 TB) at `/home` and `/shared`. The approximately 1.89 TB overlay at `/` is the server system filesystem and is distinct from the laboratory data allocation.


## 0.7.4 personal-home storage display and access guides

- Dashboard status exposes the laboratory account layout and whether a shared container uses personal homes without a common-folder mount. The Byun detail view shows one container, twelve accounts and the single 5,000 GB allocation; cards show each personal home.
- Access guides derive the personal-home layout, allocated capacity, port, native password-change support and per-account administrator role from current laboratory data. Legacy laboratories retain their existing guide fields. No password values are included.
- Korean and English guides were exported through the deployed authenticated dashboard, text-checked and visually reviewed on all two pages. They contain port 2208, 5 TB, personal home instructions and passwd, without a /shared reference.
- 111 unit tests passed, including home-only guides and unchanged legacy guide behavior. The live dashboard showed the updated layout. Only dashboard services were restarted; research containers were not restarted or replaced.
