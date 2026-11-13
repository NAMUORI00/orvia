"""Mount-first restart recovery. Never creates or replaces a container."""

import json, pathlib, re, subprocess, sys
import hotops
import lifecycle


def units(spec):
    service = spec.get("service", "")
    if not re.fullmatch(
        r"(?:labharbor-[a-z][a-z0-9-]*|h200-research[0-9]*)\.service", service
    ):
        raise ValueError("복구 서비스 설정을 확인하세요.")
    stem = service.removesuffix(".service")
    timer = (
        stem + ".timer" if service.startswith("labharbor-") else stem + "-recover.timer"
    )
    worker = service if service.startswith("labharbor-") else stem + "-recover.service"
    return service, timer, worker


def pause(spec):
    service, timer, worker = units(spec)
    active = (
        subprocess.run(["systemctl", "is-active", "--quiet", timer]).returncode == 0
    )
    # Do not stop the laboratory service: legacy ExecStop stops every researcher.
    hotops.run("systemctl", "stop", timer, worker)
    return active


def resume(spec, active):
    if active:
        hotops.run("systemctl", "start", units(spec)[1])


def recovery_path(lab):
    if not re.fullmatch("[a-z][a-z0-9-]{1,40}", lab):
        raise ValueError("Invalid laboratory ID")
    return hotops.STATE / "recovery" / (lab + ".json")


def install(lab, spec, objects):
    """Return a reversible file transaction; do not start any service."""
    service, timer, worker = units(spec)
    files = {}
    state = recovery_path(lab)
    state.parent.mkdir(mode=0o700, exist_ok=True)
    record = dict(
        schema_version=1, storage=spec["storage"], disk=spec.get("disk"), containers=[]
    )
    for o in objects:
        bridges = []
        for name in o["NetworkSettings"]["Networks"]:
            if name in ("none", "host", "bridge"):
                continue
            net = json.loads(hotops.run("docker", "network", "inspect", name))[0]
            bridge = net.get("Options", {}).get("com.docker.network.bridge.name")
            if not bridge or not re.fullmatch("[a-zA-Z0-9_-]{1,15}", bridge):
                raise ValueError("격리 네트워크를 확인하세요.")
            bridges.append(bridge)
        record["containers"].append(
            dict(
                name=o["Name"].lstrip("/"),
                image=o["Image"],
                mounts=o["Mounts"],
                gpus=o["HostConfig"].get("DeviceRequests"),
                devices=o["HostConfig"].get("Devices"),
                bridges=bridges,
            )
        )
    files[state] = state.read_bytes() if state.exists() else None
    unit_paths = []
    for unit in set([service, worker]):
        path = (
            pathlib.Path("/etc/systemd/system")
            / (unit + ".d")
            / "labharbor-recovery.conf"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        files[path] = path.read_bytes() if path.exists() else None
        unit_paths.append(path)
    try:
        hotops.save(state, record)
        for path in unit_paths:
            path.write_text(
                "[Service]\nExecStart=\nExecStart=/usr/bin/python3 /opt/h200-console/app/recovery.py "
                + lab
                + "\n"
            )
        hotops.run("systemctl", "daemon-reload")
    except Exception:
        restore(files)
        raise
    return files


def restore(files):
    for path, content in files.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)
    hotops.run("systemctl", "daemon-reload")


def recover(lab):
    p = json.loads(recovery_path(lab).read_text())
    source = hotops.run("findmnt", "-n", "-o", "SOURCE", "--mountpoint", p["storage"])
    if p.get("disk"):
        actual = json.loads(hotops.run("losetup", "--list", "--json", source))[
            "loopdevices"
        ][0]["back-file"]
        if actual != p["disk"]:
            raise ValueError("Persistent storage mismatch")
    for expected in p["containers"]:
        o = hotops.obj(expected["name"])
        if (
            o["HostConfig"].get("Privileged")
            or o["HostConfig"].get("NetworkMode") == "host"
        ):
            raise ValueError("Isolation changed")
        signature = lambda mounts: sorted(
            (m["Type"], m["Source"], m["Destination"], m["RW"]) for m in mounts
        )
        if (
            signature(o["Mounts"]) != signature(expected["mounts"])
            or o["Image"] != expected["image"]
            or o["HostConfig"].get("DeviceRequests") != expected["gpus"]
            or o["HostConfig"].get("Devices") != expected["devices"]
        ):
            raise ValueError("Environment configuration changed")
        for bridge in expected["bridges"]:
            lifecycle.firewall(
                dict(
                    uid=0,
                    bridge=bridge,
                    chain="LHR"
                    + __import__("hashlib").sha256(bridge.encode()).hexdigest()[:12],
                )
            )
        if not o["State"]["Running"]:
            hotops.run("docker", "start", expected["name"])


if __name__ == "__main__":
    recover(sys.argv[1])
