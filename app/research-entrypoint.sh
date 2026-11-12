#!/bin/bash
set -euo pipefail
[[ "$RESEARCH_USER" =~ ^[a-z][a-z0-9_]{1,30}$ ]] || exit 1
id "$RESEARCH_USER" >/dev/null
mkdir -p /run/sshd
cat > /run/sshd_config <<EOF
Port 2222
ListenAddress 0.0.0.0
HostKey /etc/research-ssh/ssh_host_ed25519_key
PidFile /run/sshd.pid
PermitRootLogin no
PasswordAuthentication yes
PermitEmptyPasswords no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
KbdInteractiveAuthentication no
UsePAM no
AllowUsers $RESEARCH_USER
AllowAgentForwarding no
AllowTcpForwarding local
PermitOpen localhost:* 127.0.0.1:* [::1]:*
GatewayPorts no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no
PermitUserRC no
MaxAuthTries 3
MaxStartups 10:30:30
LoginGraceTime 30
UseDNS no
PrintMotd no
Subsystem sftp internal-sftp
LogLevel ERROR
EOF
/usr/sbin/sshd -t -f /run/sshd_config
exec /usr/sbin/sshd -D -e -f /run/sshd_config
