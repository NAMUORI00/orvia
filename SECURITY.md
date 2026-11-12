# Security

Report vulnerabilities privately through GitHub's security reporting mechanism when enabled; do not include passwords, tokens, live account identifiers, backup archives or private server configuration in issues.

This is an early administrative tool for trusted operators, not a hardened multi-tenant hosting platform. Containers share the host kernel. A requested root-access preset does not imply kernel-level isolation or safe arbitrary privilege escalation.

Controls include a non-root web service, a root-owned Unix socket, CSRF tokens, administrator sessions, bounded resource input, lab/GPU mutation allowlists, constant official-registry URLs, root-approved provisioning, and confirmation-gated recreation of eligible managed environments. Protected-lab rejection is tested before execution of mutation commands.

Backups are sensitive and remain root-readable. Existing accounts and passwords are not bundled. Do not put real credentials in fixtures or screenshots. Avoid public exposure of the HTTP listener; use TLS or an SSH tunnel as appropriate to the deployment.
