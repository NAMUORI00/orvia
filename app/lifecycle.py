"""Execute root-approved, single-GPU provisioning plans from the console.

Plans are installed out of band by the host administrator. Browser requests can
only select an existing plan ID; they cannot choose paths, commands or images.
Credentials never appear in the public plan or job result.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time

import hotops

PLANS = pathlib.Path("/etc/h200-console/plans")
APP = pathlib.Path(__file__).resolve().parent


def run(*args, timeout=120, input=None):
    return hotops.run(*args, timeout=timeout, input=input)


def read_plan(key):
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,31}", key or ""):
        raise ValueError("Invalid plan ID")
    path = PLANS / (key + ".json")
    st = path.stat()
    if path.is_symlink() or st.st_uid != 0 or st.st_mode & 0o077:
        raise PermissionError("Plan must be root-owned and mode 600")
    return json.loads(path.read_text())


def plans():
    result = []
    for path in sorted(PLANS.glob("*.json")):
        p = read_plan(path.stem)
        result.append(
            {
                k: p.get(k)
                for k in (
                    "id",
                    "title",
                    "user",
                    "index",
                    "storage_gb",
                    "port",
                    "replace",
                )
            }
        )
    jobs = hotops.catalog()["jobs"]
    return dict(plans=result, jobs=[j for j in jobs if j.get("kind") == "provision"])


def validate(p, c):
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,23}", p["id"]):
        raise ValueError("Invalid lab ID")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", p["user"]):
        raise ValueError("Invalid user ID")
    if p["gpu"] not in c["write_gpus"]:
        raise PermissionError("GPU is protected")
    if p["id"] in c["labs"]:
        raise ValueError("Lab already exists")
    if not 1 <= int(p["storage_gb"]) <= int(c.get("provision_max_gb", 0)):
        raise ValueError("Storage exceeds provisioning policy")
    if not 1024 <= int(p["port"]) <= 65535 or not 12000 <= int(p["uid"]) <= 60000:
        raise ValueError("Invalid port or UID")
    old = c["labs"].get(p.get("replace"))
    if old is not None:
        if (
            p["replace"] not in c["write_labs"]
            or not old.get("sandbox")
            or old["gpu"] != p["gpu"]
        ):
            raise PermissionError("Only the approved test environment can be replaced")
        # Do not permit partial or drifted replacement targets.
        if [u["name"] for u in old["users"]] != p.get("replace_users"):
            raise ValueError("Replacement membership changed")
    elif p.get("replace"):
        raise ValueError("Replacement target does not exist")


def submit(req):
    key = req.get("plan", "")
    p = read_plan(key)
    if req.get("confirm") != p["id"]:
        raise ValueError("Enter the new lab ID to confirm")
    validate(p, hotops.cfg())
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("Another storage operation is running")
    job = dict(
        id="provision-" + str(time.time_ns()),
        kind="provision",
        lab=p["id"],
        state="queued",
        message="Queued",
    )
    hotops.STATE.joinpath("jobs").mkdir(exist_ok=True)
    hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
    threading.Thread(target=worker, args=(p, job), daemon=True).start()
    return {"message": "Provisioning started. Check progress below."}


def network(p):
    uid = str(p["uid"])
    net, bridge, chain = "lh-net-" + uid, "lh" + uid, "LH" + uid
    run(
        "docker",
        "network",
        "create",
        "--driver",
        "bridge",
        "--label",
        "labharbor.lab=" + p["id"],
        "--opt",
        "com.docker.network.bridge.name=" + bridge,
        "--opt",
        "com.docker.network.bridge.enable_icc=false",
        net,
    )
    firewall(p)
    return net


def firewall(p):
    bridge, chain = "lh" + str(p["uid"]), "LH" + str(p["uid"])
    if (
        subprocess.run(
            ["iptables", "-w", "-S", chain],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        attach_firewall(bridge, chain)
        return
    run("iptables", "-w", "-N", chain)
    run(
        "iptables",
        "-w",
        "-A",
        chain,
        "-m",
        "conntrack",
        "--ctstate",
        "ESTABLISHED,RELATED",
        "-j",
        "RETURN",
    )
    for cidr in [
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
    ]:
        run("iptables", "-w", "-A", chain, "-d", cidr, "-j", "REJECT")
    run(
        "iptables",
        "-w",
        "-A",
        chain,
        "-p",
        "tcp",
        "-m",
        "multiport",
        "--dports",
        "80,443",
        "-j",
        "RETURN",
    )
    run("iptables", "-w", "-A", chain, "-j", "REJECT")
    attach_firewall(bridge, chain)


def attach_firewall(bridge, chain):
    for target, args in [
        ("DOCKER-USER", ["-i", bridge, "-j", chain]),
        ("INPUT", ["-i", bridge, "-j", "REJECT"]),
    ]:
        if subprocess.run(
            ["iptables", "-w", "-C", target, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            run("iptables", "-w", "-I", target, "1", *args)


def worker(p, job):
    def progress(message):
        job.update(state="running", message=message)
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)

    try:
        c = hotops.cfg()
        validate(p, c)
        root = pathlib.Path(c["provision_root"]).resolve()
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Provisioning root is not available")
        base, disk = root / p["id"], root / (p["id"] + ".ext4")
        if base.exists() or disk.exists():
            raise ValueError("Storage already exists; inspect before retrying")
        total = int(p["storage_gb"]) * 10**9
        if shutil.disk_usage(root).free < total + 100 * 10**9:
            raise ValueError("Insufficient free space")
        actual = dict(
            line.strip().split(", ")
            for line in run(
                "nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"
            ).splitlines()
        )
        if actual.get(str(p["index"])) != p["gpu"]:
            raise ValueError("GPU mapping changed")
        # Every active container must explicitly exclude the target GPU, except the approved replacement.
        old = c["labs"].get(p.get("replace"))
        old_names = {old["prefix"] + u["name"] for u in old["users"]} if old else set()
        for ident in run("docker", "ps", "-q").split():
            o = hotops.obj(ident)
            if o["Name"].lstrip("/") not in old_names:
                for r in o["HostConfig"].get("DeviceRequests") or []:
                    if r.get("Count") == -1 or p["gpu"] in (r.get("DeviceIDs") or []):
                        raise ValueError("GPU already used by another container")
        if old:
            import broker

            for u in old["users"]:
                broker.checked_container(c, old, u)
            old_mount = run(
                "systemd-escape", "--path", "--suffix=mount", old["storage"]
            )
            dependencies = run(
                "systemctl",
                "show",
                "h200-console-broker.service",
                "--property=Requires",
                "--value",
            ).split()
            if old_mount in dependencies:
                raise ValueError(
                    "Remove the broker dependency on the retiring test mount before applying this plan"
                )
        name = "lh-" + p["id"] + "-" + p["user"]
        # Reserve port before allocating storage. Docker validates it again on start.
        import socket

        with socket.socket() as probe:
            probe.bind((p["bind_ip"], int(p["port"])))
        progress("Preparing isolated research image")
        stage = hotops.STATE / "changes" / job["id"]
        stage.mkdir(parents=True, mode=0o700)
        shutil.copy(APP / "research-entrypoint.sh", stage / "entrypoint.sh")
        # No credentials in build layers, command arguments or build logs.
        source = p["source_image"]
        if hotops.obj(source)["Id"] != p["source_image_id"]:
            raise ValueError("Approved source image changed")
        (stage / "Dockerfile").write_text(
            f"FROM {source}\nRUN groupadd -g {p['uid']} {p['user']} && useradd -u {p['uid']} -g {p['uid']} -M -s /bin/bash {p['user']}\n"
            "COPY entrypoint.sh /usr/local/sbin/research-entrypoint\nRUN chmod 755 /usr/local/sbin/research-entrypoint\n"
        )
        image = run("docker", "build", "-q", "--network=none", str(stage), timeout=300)
        shadow = run(
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint",
            "/bin/cat",
            image,
            "/etc/shadow",
        )
        rows = []
        for line in shadow.splitlines():
            fields = line.split(":")
            fields[1] = p["password_hash"] if fields[0] == p["user"] else "!"
            rows.append(":".join(fields))
        progress("Allocating persistent storage")
        base.mkdir(mode=0o755)
        run("fallocate", "-l", str(total), str(disk))
        disk.chmod(0o600)
        run(
            "mkfs.ext4",
            "-q",
            "-m",
            "0",
            "-E",
            "nodiscard,lazy_itable_init=1,lazy_journal_init=1",
            str(disk),
            timeout=300,
        )
        unit = run("systemd-escape", "--path", "--suffix=mount", str(base))
        pathlib.Path("/etc/systemd/system", unit).write_text(
            "[Unit]\nDescription=LabHarbor persistent storage\nRequiresMountsFor="
            + str(root)
            + "\n[Mount]\nWhat="
            + str(disk)
            + "\nWhere="
            + str(base)
            + "\nType=ext4\nOptions=loop,nosuid,nodev\n[Install]\nWantedBy=multi-user.target\n"
        )
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", unit)
        admin = base / ".admin" / p["user"]
        admin.mkdir(parents=True, mode=0o700)
        (base / ".admin").chmod(0o700)
        (admin / "shadow").write_text("\n".join(rows) + "\n")
        (admin / "shadow").chmod(0o600)
        keys = admin / "ssh"
        keys.mkdir(mode=0o700)
        run(
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(keys / "ssh_host_ed25519_key"),
        )
        home = base / p["user"]
        home.mkdir(mode=0o700)
        for directory in [".tmp", ".cache", ".conda"]:
            (home / directory).mkdir(mode=0o700)
        (home / ".bashrc").write_text(". /etc/profile.d/research.sh\n")
        (home / ".bash_profile").write_text(". ~/.bashrc\n")
        for path in [home, *home.iterdir()]:
            os.chown(path, p["uid"], p["uid"])
        progress("Starting isolated account")
        net = network(p)
        args = [
            "docker",
            "create",
            "--name",
            name,
            "--hostname",
            name,
            "--label",
            "labharbor.lab=" + p["id"],
            "--restart",
            "no",
            "--network",
            net,
            "--publish",
            f"{p['bind_ip']}:{p['port']}:2222",
            "--read-only",
            "--security-opt",
            "no-new-privileges:true",
            "--cap-drop",
            "ALL",
            "--pids-limit",
            "4096",
            "--shm-size",
            "1g",
            "--log-driver",
            "none",
            "--sysctl",
            "net.ipv6.conf.all.disable_ipv6=1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=1073741824,mode=1777",
            "--tmpfs",
            "/run:rw,nosuid,nodev,size=16777216,mode=755",
            "--gpus",
            "device=" + p["gpu"],
            "--env",
            "RESEARCH_USER=" + p["user"],
            "--env",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            "--workdir",
            "/home/" + p["user"],
        ]
        for src, dst, ro in [
            (home, "/home/" + p["user"], False),
            (admin / "shadow", "/etc/shadow", True),
            (keys, "/etc/research-ssh", True),
        ]:
            args += [
                "--mount",
                f"type=bind,src={src},dst={dst}" + (",readonly" if ro else ""),
            ]
        for device in [
            f"/dev/nvidia{p['index']}",
            "/dev/nvidiactl",
            "/dev/nvidia-uvm",
            "/dev/nvidia-uvm-tools",
        ]:
            args += ["--device", device + ":" + device + ":rw"]
        for cap in [
            "CHOWN",
            "DAC_OVERRIDE",
            "FOWNER",
            "SETGID",
            "SETUID",
            "SYS_CHROOT",
            "AUDIT_WRITE",
            "KILL",
        ]:
            args += ["--cap-add", cap]
        run(*args, image)
        run("docker", "start", name)
        for attempt in range(20):
            try:
                run(
                    "docker",
                    "exec",
                    name,
                    "/usr/sbin/sshd",
                    "-t",
                    "-f",
                    "/run/sshd_config",
                )
                break
            except subprocess.CalledProcessError:
                if attempt == 19:
                    raise
                time.sleep(0.5)
        visible = run(
            "docker",
            "exec",
            "--user",
            str(p["uid"]),
            name,
            "nvidia-smi",
            "--query-gpu=uuid",
            "--format=csv,noheader",
        )
        if visible.strip() != p["gpu"]:
            raise ValueError("New account GPU isolation check failed")
        spec = dict(
            title=p["title"],
            index=p["index"],
            gpu=p["gpu"],
            users=[dict(name=p["user"], uid=p["uid"], port=p["port"])],
            storage=str(base),
            disk=str(disk),
            prefix="lh-" + p["id"] + "-",
            managed=True,
            source_image=p["source_image"],
            sandbox=False,
        )
        # Recovery starts only this existing container after checking its mount; never recreates it.
        recovery = hotops.STATE / "changes" / (p["id"] + "-recovery.json")
        hotops.save(
            recovery,
            dict(
                container=name,
                storage=str(base),
                disk=str(disk),
                gpu=p["gpu"],
                uid=p["uid"],
            ),
        )
        service = "labharbor-" + p["id"] + ".service"
        pathlib.Path("/etc/systemd/system", service).write_text(
            "[Unit]\nDescription=LabHarbor research account\nRequires=docker.service "
            + unit
            + "\nAfter=docker.service "
            + unit
            + "\n"
            "[Service]\nType=oneshot\nExecStart=/usr/bin/python3 "
            + str(APP / "lifecycle.py")
            + " recover "
            + str(recovery)
            + "\n[Install]\nWantedBy=multi-user.target\n"
        )
        timer = "labharbor-" + p["id"] + ".timer"
        pathlib.Path("/etc/systemd/system", timer).write_text(
            "[Unit]\nDescription=LabHarbor account recovery\n[Timer]\nOnBootSec=60\nOnUnitActiveSec=60\nUnit="
            + service
            + "\n[Install]\nWantedBy=timers.target\n"
        )
        spec["service"] = service
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", service, timer)
        # Re-read policy to preserve concurrent metadata changes.
        c = hotops.cfg()
        validate(p, c)
        c["labs"][p["id"]] = spec
        c["write_labs"].append(p["id"])
        hotops.save(hotops.ETC / "policy.json", c)
        if old:
            progress("Removing the approved test environment")
            retire(p, c, old, stage)
        job.update(state="complete", message="연구실 생성 완료", lab=p["id"])
        # Credential-bearing plan has served its purpose; keep no second copy.
        (PLANS / (p["id"] + ".json")).unlink()
        shutil.rmtree(stage)
    except Exception as exc:
        # Fail closed: preserve partial resources for inspection, never delete on failure.
        job.update(
            state="failed",
            message=str(exc)
            if isinstance(exc, (ValueError, PermissionError))
            else "Provisioning stopped. Inspect the server job log before retrying.",
        )
        import logging

        logging.exception("Provisioning failed for %s", p.get("id"))
    finally:
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        hotops.JOB_LOCK.release()


def retire(p, c, old, stage):
    import broker

    # Verify all targets again before deleting anything. No path supplied by the browser.
    for u in old["users"]:
        broker.checked_container(c, old, u)
    disk = pathlib.Path(old["disk"])
    base = pathlib.Path(old["storage"])
    if (
        disk.is_symlink()
        or base.is_symlink()
        or disk.parent != base.parent
        or base.parent != pathlib.Path("/raid")
    ):
        raise ValueError("Unexpected replacement storage location")
    source = run("findmnt", "-n", "-o", "SOURCE", "--mountpoint", str(base))
    backing = json.loads(run("losetup", "--list", "--json", source))["loopdevices"][0][
        "back-file"
    ]
    if pathlib.Path(backing) != disk:
        raise ValueError("Replacement disk mapping changed")
    # Keep a small recoverable archive of the old test files before removing their disk.
    archive = hotops.STATE / "changes" / (p["id"] + "-retired-test.tar")
    for u in old["users"]:
        run("docker", "stop", "-t", "15", old["prefix"] + u["name"])
    run("tar", "-cpf", str(archive), "-C", str(base), ".", timeout=300)
    archive.chmod(0o600)
    for u in old["users"]:
        run("docker", "rm", old["prefix"] + u["name"])
    unit = run("systemd-escape", "--path", "--suffix=mount", str(base))
    run("systemctl", "disable", "--now", unit)
    disk.unlink()
    base.rmdir()
    pathlib.Path("/etc/systemd/system", unit).unlink()
    run("systemctl", "daemon-reload")
    c = hotops.cfg()
    del c["labs"][p["replace"]]
    c["write_labs"].remove(p["replace"])
    hotops.save(hotops.ETC / "policy.json", c)


def recover(path):
    p = json.loads(pathlib.Path(path).read_text())
    source = run("findmnt", "-n", "-o", "SOURCE", "--mountpoint", p["storage"])
    if (
        json.loads(run("losetup", "--list", "--json", source))["loopdevices"][0][
            "back-file"
        ]
        != p["disk"]
    ):
        raise ValueError("Persistent storage mismatch")
    o = hotops.obj(p["container"])
    if o["HostConfig"]["Privileged"] or o["HostConfig"]["DeviceRequests"][0][
        "DeviceIDs"
    ] != [p["gpu"]]:
        raise ValueError("Container isolation changed")
    firewall(p)
    if not o["State"]["Running"]:
        run("docker", "start", p["container"])


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "recover":
        recover(sys.argv[2])
