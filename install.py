#!/usr/bin/env python3
"""Orvia installer: installs only its own services; never creates research containers."""

import argparse, getpass, hashlib, ipaddress, json, os, pathlib, platform, pwd, re, secrets, shutil, socket, subprocess, sys, time

SRC = pathlib.Path(__file__).resolve().parent
APP = pathlib.Path("/opt/h200-console")
ETC = pathlib.Path("/etc/h200-console")
STATE = pathlib.Path("/var/lib/h200-console")
UNITS = pathlib.Path("/etc/systemd/system")


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def cmd(*args):
    subprocess.run(args, check=True)


def preflight():
    if sys.platform != "linux" or not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise SystemExit("Linux with Python 3.10-3.12 is required.")
    missing = [
        x
        for x in [
            "docker",
            "nvidia-smi",
            "systemctl",
            "useradd",
            "tar",
            "findmnt",
            "losetup",
            "resize2fs",
        ]
        if not shutil.which(x)
    ]
    if missing:
        raise SystemExit("Install prerequisites first: " + ", ".join(missing))
    run("docker", "info", "--format", "{{.ServerVersion}}")
    run("nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader")
    print("Prerequisites OK. Research containers are not modified.")


def units(host, port):
    broker = """[Unit]
Description=Orvia control broker
After=docker.service
[Service]
ExecStart=/usr/bin/python3 /opt/h200-console/app/broker.py
RuntimeDirectory=h200-console
RuntimeDirectoryMode=0750
Group=h200-console
UMask=0077
Restart=on-failure
MemoryMax=1G
CPUQuota=100%
NoNewPrivileges=yes
ProtectSystem=full
[Install]
WantedBy=multi-user.target
"""
    web = f"""[Unit]
Description=Orvia web
After=h200-console-broker.service
Requires=h200-console-broker.service
[Service]
User=h200-console
Group=h200-console
WorkingDirectory=/opt/h200-console/app
Environment=H200_TRUSTED_HOSTS=127.0.0.1,localhost,{host}
ExecStart=/opt/h200-console/venv/bin/gunicorn --workers 1 --threads 4 --timeout 180 --bind {host}:{port} web:app
Restart=on-failure
MemoryMax=512M
CPUQuota=100%
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
[Install]
WantedBy=multi-user.target
"""
    return broker, web


def dependencies():
    cmd(sys.executable, "-m", "venv", "--without-pip", str(APP / "venv"))
    wheel = (
        next((SRC / "wheels").glob("pip-*.whl"), None)
        if (SRC / "wheels").exists()
        else None
    )
    py = str(APP / "venv/bin/python")
    if wheel:
        cmd(
            py,
            "-c",
            'import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("pip",run_name="__main__")',
            str(wheel),
            "install",
            "--no-index",
            str(wheel),
        )
    else:
        cmd(py, "-m", "ensurepip")
    args = [py, "-m", "pip", "install", "--disable-pip-version-check"]
    if wheel and sys.version_info[:2] == (3, 10) and platform.machine() == "x86_64":
        args += ["--no-index", "--find-links", str(SRC / "wheels")]
    cmd(*args, "-r", str(SRC / "requirements.txt"))


def tree_permissions():
    APP.chmod(0o755)
    for root, dirs, files in os.walk(APP):
        os.chmod(root, 0o755)
        for n in files:
            p = pathlib.Path(root) / n
            if not p.is_symlink():
                p.chmod(0o755 if os.access(p, os.X_OK) else 0o644)


def install():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo.")
    preflight()
    if any(p.exists() for p in [APP, ETC, STATE]):
        raise SystemExit(
            "Existing installation detected. Use: sudo python3 install.py --update"
        )
    print("\nOrvia setup — research containers stay unchanged\n")
    username = input("Administrator ID [admin]: ").strip() or "admin"
    if not re.fullmatch("[A-Za-z][A-Za-z0-9_-]{2,31}", username):
        raise SystemExit("Invalid administrator ID.")
    password = getpass.getpass("Administrator password (10+ characters): ")
    if len(password) < 10 or password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords must match and contain at least 10 characters.")
    host = input("Listen IP [127.0.0.1]: ").strip() or "127.0.0.1"
    ipaddress.IPv4Address(host)
    if host == "0.0.0.0":
        raise SystemExit("Choose a specific local IP address.")
    port = int(input("Web port [18600]: ").strip() or 18600)
    with socket.socket() as sock:
        sock.bind((host, port))
    backup = pathlib.Path(
        input("Backup directory [/var/lib/labharbor/backups]: ").strip()
        or "/var/lib/labharbor/backups"
    )
    if not backup.is_absolute() or any(c in str(backup) for c in ["\n", "\r"]):
        raise SystemExit("Use an absolute backup path.")
    rows = [
        x.split(",")
        for x in run(
            "nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"
        ).splitlines()
    ]
    for i, u in rows:
        print(i.strip(), u.strip())
    chosen = input(
        "GPU indexes allowed for changes (comma-separated; empty = monitoring only): "
    ).strip()
    indexes = {x.strip() for x in chosen.split(",") if x.strip()}
    known = {i.strip(): u.strip() for i, u in rows}
    if not indexes.issubset(known):
        raise SystemExit("Unknown GPU index.")
    os.umask(0o077)
    for p in [APP, ETC, STATE]:
        p.mkdir(mode=0o700)
    try:
        account = pwd.getpwnam("h200-console")
        assert (
            account.pw_shell == "/usr/sbin/nologin" and account.pw_dir == "/nonexistent"
        )
    except KeyError:
        cmd(
            "useradd",
            "--system",
            "--user-group",
            "--home-dir",
            "/nonexistent",
            "--shell",
            "/usr/sbin/nologin",
            "h200-console",
        )
    gid = pwd.getpwnam("h200-console").pw_gid
    shutil.copytree(
        SRC / "app", APP / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    dependencies()
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 1000000
    ).hex()
    (ETC / "web.json").write_text(
        json.dumps(
            dict(
                username=username,
                access_host=host,
                secret=secrets.token_urlsafe(48),
                password_hash=f"pbkdf2:sha256:1000000${salt}${hashed}",
            )
        )
    )
    (ETC / "web.json").chmod(0o640)
    os.chown(ETC / "web.json", 0, gid)
    ETC.chmod(0o750)
    os.chown(ETC, 0, gid)
    (ETC / "policy.json").write_text(
        json.dumps(
            dict(
                labs={},
                write_labs=[],
                write_gpus=[known[i] for i in indexes],
                max_storage_gb=10000,
                backup_root=str(backup),
            )
        )
    )
    tree_permissions()
    broker, web = units(host, port)
    for name, content in [("broker", broker), ("web", web)]:
        p = UNITS / ("h200-console-" + name + ".service")
        p.write_text(content)
        p.chmod(0o644)
    cmd("systemctl", "daemon-reload")
    cmd(
        "systemctl",
        "enable",
        "--now",
        "h200-console-broker.service",
        "h200-console-web.service",
    )
    print(
        f"Open http://{host}:{port} and register existing containers. Use HTTPS or an SSH tunnel on untrusted networks."
    )


def update():
    if os.geteuid() != 0 or not (ETC / "web.json").exists():
        raise SystemExit("Run as root on an existing installation.")
    preflight()
    dependencies()
    backup = APP / ("app.backup-" + time.strftime("%Y%m%d%H%M%S"))
    stage = APP / "app.next"
    if stage.exists():
        raise SystemExit("Unfinished update staging directory exists.")
    shutil.copytree(SRC / "app", stage, ignore=shutil.ignore_patterns("__pycache__"))
    cmd("systemctl", "stop", "h200-console-web.service", "h200-console-broker.service")
    (APP / "app").rename(backup)
    stage.rename(APP / "app")
    tree_permissions()
    cmd("systemctl", "start", "h200-console-broker.service", "h200-console-web.service")
    print("Updated. Previous application:", backup)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--update", action="store_true")
    a = p.parse_args()
    if a.check:
        preflight()
    elif a.update:
        update()
    else:
        install()
