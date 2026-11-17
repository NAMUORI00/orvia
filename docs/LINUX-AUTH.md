# Linux administrator authentication

Orvia authenticates host Linux credentials using the `orvia` PAM service (`common-auth` and `common-account` on Ubuntu). It checks the actual sudo policy for `/usr/bin/python3 -I /opt/h200-console/app/session_worker.py`. Root, locked accounts and non-login shells are rejected. Container accounts do not grant host access.

The broker launches sudo as the authenticated host UID and supplementary groups. Sudo authenticates and opens a privileged, bounded management worker with the genuine SUDO_USER/SUDO_UID. Restricted sudo accounts that cannot run this management worker cannot log in. No additional sudoers rule or NOPASSWD grant is installed. Passwords are neither written to the application database nor retained after authentication.

Sessions expire after 30 minutes and logout closes their worker. Account validity and sudo policy are checked on each request. Previously accepted background jobs finish before the worker exits; a global file lock serializes management operations across sessions. Worker process restart invalidates sessions. Linux sudo logs record the worker invocation, and Orvia audit JSON plus the system journal record the actor, action, target and result. This is privileged execution through that user's sudo authority, not an unprivileged shell or arbitrary terminal.

The web service retains NoNewPrivileges=yes. The root broker needs NoNewPrivileges=no so its child can drop to the authenticated UID and then actually invoke sudo. The worker source and application directory must be root-owned and not writable by unprivileged accounts. Linux passwords should be transmitted over HTTPS or an SSH tunnel on untrusted networks.

Use `sudo passwd USER` and the host sudoers policy to manage access. There is no separate Orvia administrator password. On an upgrade, back up web.json, apply the PAM service and broker drop-in, remove username/password_hash from web.json, and restart only the two dashboard services. Research containers are not restarted.
