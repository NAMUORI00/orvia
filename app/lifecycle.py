"""Execute root-approved, single-GPU provisioning plans from the console.

Plans are installed out of band by the host administrator. Browser requests can
select an existing plan ID and a validated folder name under the configured
storage root; they cannot choose arbitrary paths, commands or images.
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
                    "storage_name",
                    "official_image",
                    "source_label",
                )
            }
        )
    jobs = hotops.catalog()["jobs"]
    return dict(
        plans=result,
        jobs=[j for j in jobs if j.get("kind") == "provision"],
        storage_root=hotops.cfg().get("provision_root", ""),
        storage_max_gb=hotops.cfg().get("provision_max_gb", 0),
    )


def sources():
    catalog = hotops.catalog()
    ids = list({u["image"] for lab in catalog["labs"] for u in lab["users"]})
    images = (
        {o["Id"]: o for o in json.loads(run("docker", "image", "inspect", *ids))}
        if ids
        else {}
    )
    result = []
    seen = set()
    for lab in catalog["labs"]:
        for user in lab["users"]:
            if user["image"] in seen:
                continue
            seen.add(user["image"])
            info = images.get(user["image"], {})
            tags = [
                t
                for t in info.get("RepoTags", []) or []
                if not t.startswith("labharbor-base:")
            ]
            result.append(
                dict(
                    title=lab["title"],
                    source=user["container"],
                    image=user["image"],
                    label=tags[0] if tags else user["image"][:19],
                )
            )
    refs = [
        ref
        for ref in run(
            "docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"
        ).splitlines()
        if ref.startswith(("nvidia/cuda:", "nvcr.io/nvidia/pytorch:"))
        and "<none>" not in ref
    ]
    bases = []
    for info in json.loads(run("docker", "image", "inspect", *refs)) if refs else []:
        layers = info.get("RootFS", {}).get("Layers", [])
        if not layers or not any(
            o.get("RootFS", {}).get("Layers", [])[: len(layers)] == layers
            for o in images.values()
        ):
            continue
        for ref in info.get("RepoTags", []) or []:
            if ref not in refs:
                continue
            repo, tag = ref.rsplit(":", 1)
            bases.append(
                dict(
                    label=ref,
                    provider="cuda" if repo == "nvidia/cuda" else "pytorch",
                    tag=tag,
                )
            )
    return dict(registered=result, bases=bases)


def storage_name(p):
    value = p.get("storage_name") or p["id"]
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", value):
        raise ValueError(
            "저장 폴더명은 영문 소문자로 시작하는 2~32자의 영문·숫자·하이픈·밑줄만 사용할 수 있습니다."
        )
    return value


def storage_paths(root, p):
    name = storage_name(p)
    base, disk = root / name, root / (name + ".ext4")
    if any(path.exists() or path.is_symlink() for path in (base, disk)):
        raise ValueError("이미 사용 중인 저장 폴더명입니다. 다른 이름을 입력하세요.")
    return base, disk


def validate(p, c):
    storage_name(p)
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,23}", p["id"]):
        raise ValueError("Invalid lab ID")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", p["user"]):
        raise ValueError("Invalid user ID")
    if p["gpu"] not in c["write_gpus"]:
        raise PermissionError("GPU is protected")
    for spec in c["labs"].values():
        for user in spec["users"]:
            if (
                user.get("name") == p["user"]
                or user.get("uid") == p["uid"]
                or user.get("port") == p["port"]
            ):
                raise ValueError("Account, UID or port is already allocated")
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
    if req.get("storage_name") is not None:
        p["storage_name"] = req["storage_name"]
        if not p["storage_name"]:
            raise ValueError("저장 폴더명을 입력하세요.")
    if req.get("confirm") != p["id"]:
        raise ValueError("Enter the new lab ID to confirm")
    c = hotops.cfg()
    validate(p, c)
    storage_paths(pathlib.Path(c["provision_root"]), p)
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
    bridge, chain = (
        p.get("bridge", "lh" + str(p["uid"])),
        p.get("chain", "LH" + str(p["uid"])),
    )
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
        base, disk = storage_paths(root, p)
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
                    if (
                        r.get("Count") == -1 or p["gpu"] in (r.get("DeviceIDs") or [])
                    ) and not p.get("allow_shared_gpu", False):
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
        official = p.get("official_image")
        if official:
            if official != __import__("environments").reference(
                p.get("image_provider"), p.get("image_tag")
            ):
                raise ValueError("Invalid official image plan")
            progress("Preparing official provider image")
            if p.get("official_image_id"):
                source = hotops.obj(p["official_image_id"])["Id"]
            else:
                run("docker", "pull", official, timeout=1800)
                source = hotops.obj(official)["Id"]
        elif hotops.obj(source)["Id"] != p["source_image_id"]:
            raise ValueError("Approved source image changed")
        (stage / "research.sh").write_text(
            "export PATH=/opt/conda/bin:$PATH\nexport TMPDIR=$HOME/.tmp\nexport XDG_CACHE_HOME=$HOME/.cache\nexport CONDA_ENVS_PATH=$HOME/.conda/envs\n"
        )
        setup = (
            "RUN command -v apt-get && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server python3 python3-venv python3-pip git ca-certificates && rm -rf /var/lib/apt/lists/*\n"
            if official
            else ""
        )
        (stage / "Dockerfile").write_text(
            f"FROM {hotops.build_source(source)}\nUSER root\n"
            + setup
            + f"RUN groupadd -g {p['uid']} {p['user']} && useradd -u {p['uid']} -g {p['uid']} -M -s /bin/bash {p['user']}\n"
            "COPY entrypoint.sh /usr/local/sbin/research-entrypoint\nRUN chmod 755 /usr/local/sbin/research-entrypoint\n"
            'COPY research.sh /etc/profile.d/research.sh\nRUN chmod 644 /etc/profile.d/research.sh\nENTRYPOINT ["/usr/local/sbin/research-entrypoint"]\nCMD []\n'
        )
        image = run(
            "docker",
            "build",
            "-q",
            "--memory=4g",
            "--cpu-quota=200000",
            "--network=" + ("default" if official else "none"),
            str(stage),
            timeout=1800 if official else 300,
        )
        run(
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "test -x /usr/sbin/sshd && test -x /usr/local/sbin/research-entrypoint && python3 --version",
            timeout=30,
        )
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
            "[Unit]\nDescription=Orvia persistent storage\nRequiresMountsFor="
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
            users=[
                dict(
                    name=p["user"],
                    uid=p["uid"],
                    port=p["port"],
                    profile=p.get("profile", {}),
                )
            ],
            storage=str(base),
            disk=str(disk),
            prefix="lh-" + p["id"] + "-",
            managed=True,
            source_image=official or p["source_image"],
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
            "[Unit]\nDescription=Orvia research account\nRequires=docker.service "
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
            "[Unit]\nDescription=Orvia account recovery\n[Timer]\nOnBootSec=60\nOnUnitActiveSec=60\nUnit="
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
        info = run(
            "docker",
            "exec",
            name,
            "/bin/sh",
            "-c",
            "python3 --version; if test -x /opt/conda/bin/conda; then /opt/conda/bin/conda --version; fi",
            timeout=20,
        )
        web_path = hotops.ETC / "web.json"
        if web_path.exists():
            config = json.loads(web_path.read_text())
            profile = config.setdefault("document_labs", {}).setdefault(p["id"], {})
            description = (official or p.get("source_label") or source) + "\n" + info
            profile.update(
                schema_version=1, environment_ko=description, environment_en=description
            )
            meta = web_path.stat()
            temp = web_path.with_suffix(".next")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2))
            os.chmod(temp, meta.st_mode & 0o777)
            os.chown(temp, meta.st_uid, meta.st_gid)
            temp.replace(web_path)
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


def prepare(req):
    """Create a private hashed plan from authenticated UI fields and registered images."""
    import crypt, pwd, socket

    c = hotops.cfg()
    key = req.get("id", "")
    name = req.get("new_user", "")
    title = req.get("title", "").strip()
    if not re.fullmatch("[a-z][a-z0-9-]{2,23}", key) or not 1 <= len(title) <= 100:
        raise ValueError("연구실 ID와 이름을 확인하세요.")
    if not re.fullmatch("[a-z][a-z0-9_]{1,30}", name):
        raise ValueError("계정 ID를 확인하세요.")
    password = req.get("password", "")
    if not 8 <= len(password) <= 128 or any(ord(x) < 32 for x in password):
        raise ValueError("8자 이상의 비밀번호를 입력하세요.")
    if any(u["name"] == name for s in c["labs"].values() for u in s["users"]):
        raise ValueError("이미 존재하는 계정입니다.")
    options = {
        hotops.name(s, u): (s, u) for s in c["labs"].values() for u in s["users"]
    }
    official = None
    official_id = None
    if req.get("image_mode", "registered") == "official":
        official = __import__("environments").reference(
            req.get("image_provider"), req.get("image_tag")
        )
        try:
            official_id = hotops.obj(official)["Id"]
        except subprocess.CalledProcessError:
            pass
        if not req.get("source_container"):
            req = dict(req, source_container=next(iter(options), ""))
    elif req.get("image_mode", "registered") != "registered":
        raise ValueError("Invalid image source")
    if req.get("source_container") not in options:
        raise ValueError("기준 개발환경을 선택하세요.")
    source = hotops.obj(req["source_container"])
    image = source["Image"]
    actual = dict(
        line.strip().split(", ")
        for line in run(
            "nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"
        ).splitlines()
    )
    index = str(req.get("gpu_index", ""))
    if index not in actual:
        raise ValueError("GPU를 선택하세요.")
    gpu = actual[index]
    usage = __import__("reconfigure").inventory()[int(index)]
    if (usage["util"] > 0 or usage["used"] > 32) and req.get("ack_shared") != "yes":
        raise ValueError("사용 중인 GPU의 공유 배정을 확인하세요.")
    if (
        any(gpu in s.get("gpus", [s["gpu"]]) for s in c["labs"].values())
        and req.get("ack_shared") != "yes"
    ):
        raise ValueError("이미 배정된 GPU의 공유 사용을 확인하세요.")
    pending = [read_plan(p.stem) for p in PLANS.glob("*.json")]
    if any(p["user"] == name for p in pending):
        raise ValueError("같은 계정의 생성 설정이 이미 있습니다.")
    used = (
        {u["uid"] for s in c["labs"].values() for u in s["users"]}
        | {u.pw_uid for u in pwd.getpwall()}
        | {p["uid"] for p in pending}
    )
    uid = next(i for i in range(12000, 60001) if i not in used)
    bindings = source["HostConfig"].get("PortBindings", {}).get("2222/tcp")
    if not bindings:
        raise ValueError("SSH 기반 연구환경을 선택하세요.")
    host = bindings[0].get("HostIp") or "0.0.0.0"
    port = None
    ports = {u["port"] for s in c["labs"].values() for u in s["users"]} | {
        p["port"] for p in pending
    }
    for candidate in range(2201, 65000):
        if candidate in ports:
            continue
        with socket.socket() as sock:
            try:
                sock.bind((host, candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise ValueError("사용 가능한 접속 포트가 없습니다.")
    import account_profile

    profile = account_profile.clean(req)
    profile["joined_on"] = profile["joined_on"] or time.strftime("%Y-%m-%d")
    p = dict(
        id=key,
        title=title,
        user=name,
        uid=uid,
        port=port,
        bind_ip=host,
        gpu=gpu,
        index=int(index),
        storage_gb=int(req.get("storage_gb", 0)),
        storage_name=req.get("storage_name") or key,
        source_image=image,
        source_image_id=image,
        official_image=official,
        official_image_id=official_id,
        source_label=official or image,
        image_provider=req.get("image_provider") if official else None,
        image_tag=req.get("image_tag") if official else None,
        password_hash=crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512)),
        profile=profile,
        replace=None,
        allow_shared_gpu=req.get("ack_shared") == "yes",
    )
    validate(p, c)
    storage_paths(pathlib.Path(c["provision_root"]), p)
    PLANS.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = PLANS / (key + ".json")
    if path.exists():
        raise ValueError("같은 ID의 생성 설정이 이미 있습니다.")
    hotops.save(path, p)
    return {"message": "연구실 생성 설정을 준비했습니다. 내용을 확인하고 적용하세요."}
