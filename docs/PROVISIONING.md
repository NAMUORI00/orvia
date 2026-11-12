# Administrator-approved provisioning

The `/provision` screen executes a host administrator's pre-approved plan.
It accepts a storage folder name under the configured storage root, but no arbitrary image, absolute path or shell parameters from the browser.
Existing imported laboratories remain protected by the GPU and lab allowlists.

The administrator installs mode-600, root-owned JSON files under
`/etc/h200-console/plans/<id>.json`. Required fields are `id`, `title`, `user`,
`uid` (12000–60000), `port`, `bind_ip`, `index`, `gpu` (UUID), `storage_gb`,
`source_image`, `source_image_id` and `password_hash` (Linux SHA-512 crypt).
Never commit these files. A completed plan is removed; hashes only remain in
the account's root-owned persistent shadow file.

Policy must explicitly define `provision_root` (an existing local directory)
and `provision_max_gb`. The image must already exist and provide OpenSSH,
Tini and the research development environment. This feature does not download
images or install packages into running researcher containers.

Optional `replace` and `replace_users` fields identify an approved **sandbox**
to retire after the new account starts. Production lab replacement is rejected.
Retired test files remain in a root-only tar archive under the state changes
directory. Failed operations preserve partial resources for administrator
inspection; retrying over an existing storage path is rejected.

The broker requires write access to `/etc/h200-console` and
`/etc/systemd/system` under its systemd filesystem protection. It must not
depend on a test mount that the plan retires. No Docker daemon or host restart
is needed. Newly provisioned accounts have read-only root filesystems, locked
root login, private home binds, a single GPU and restricted outbound networking.
CPU and RAM are shared by default. Storage uses a preallocated ext4 loop image.

Recovery timers verify the backing storage and the existing container, restore
scoped network rules and start the container if stopped. They never recreate
containers. Full host reboot and fresh-server provisioning require separate
validation before being claimed as tested.

## Storage folder names

An optional `storage_name` defaults to the lab ID. The creation form can override it with 2–32 lowercase letters, digits, hyphens or underscores, beginning with a letter. Both folder and `.ext4` filename are checked for collisions, including dangling symlinks, before submission and again before allocation. Lab identity and container naming remain separate from the storage folder.

Existing lab storage paths and backing files are visible on the storage page, but are not editable. This feature does not rename live mounts, relocate data or recreate existing containers.
