"""Transactional laboratory GPU reassignment with retained containers and bind data."""

import copy, hashlib, json, pathlib, subprocess, time, uuid
from urllib.parse import quote
import hotops, maintenance, recovery


def fingerprint(objects):
    return hashlib.sha256(
        json.dumps(sorted((o["Id"], o["State"]["StartedAt"]) for o in objects)).encode()
    ).hexdigest()


def inventory():
    result = {}
    for line in hotops.run(
        "nvidia-smi",
        "--query-gpu=index,uuid,utilization.gpu,memory.used",
        "--format=csv,noheader,nounits",
    ).splitlines():
        i, g, util, used = [v.strip() for v in line.split(",")]
        result[int(i)] = dict(uuid=g, util=int(util), used=int(used))
    return result


def payload(original, indices, devices):
    p = maintenance.create_payload(original)
    p["HostConfig"]["DeviceRequests"] = [
        dict(
            Driver="nvidia",
            Count=0,
            DeviceIDs=devices,
            Capabilities=[["gpu"]],
            Options={},
        )
    ]
    common = [
        d
        for d in p["HostConfig"].get("Devices", [])
        if not __import__("re").fullmatch(r"/dev/nvidia\d+", d["PathOnHost"])
    ]
    p["HostConfig"]["Devices"] = common + [
        dict(
            PathOnHost="/dev/nvidia" + str(i),
            PathInContainer="/dev/nvidia" + str(i),
            CgroupPermissions="rwm",
        )
        for i in indices
    ]
    env = [e for e in p.get("Env", []) if not e.startswith("NVIDIA_VISIBLE_DEVICES=")]
    p["Env"] = env + ["NVIDIA_VISIBLE_DEVICES=" + ",".join(devices)]
    return p


def apply(req, images=None, lock_owned=False, source_image=None, root_access=False):
    c = hotops.cfg()
    lab = req.get("lab")
    spec = c["labs"].get(lab)
    if not spec or lab not in c["write_labs"]:
        raise PermissionError("등록된 관리 대상 연구실을 선택하세요.")
    if (
        req.get("confirm") != lab
        or req.get("ack_downtime") != "yes"
        or req.get("ack_recreate") != "yes"
    ):
        raise ValueError("대상 연구실과 작업 중단을 확인하세요.")
    try:
        indices = sorted(set(int(i) for i in req.get("gpu_selection", "").split(",")))
    except ValueError:
        raise ValueError("GPU를 선택하세요.") from None
    known = inventory()
    if not indices or any(i not in known for i in indices):
        raise ValueError("GPU를 선택하세요.")
    devices = [known[i]["uuid"] for i in indices]
    if any(g not in c["write_gpus"] for g in devices):
        raise PermissionError("관리 범위 밖의 GPU입니다.")
    other = {
        g
        for key, s in c["labs"].items()
        if key != lab
        for g in s.get("gpus", [s["gpu"]])
    }
    old_devices = spec.get("gpus", [spec["gpu"]])
    occupied = any(g in other for g in devices) or any(
        (known[i]["util"] > 0 or known[i]["used"] > 32)
        and known[i]["uuid"] not in old_devices
        for i in indices
    )
    if occupied and req.get("ack_shared") != "yes":
        raise ValueError("사용 중인 GPU의 공유 배정을 확인하세요.")
    objects = []
    for u in spec["users"]:
        _, _, _, o = hotops.authorize(dict(req, user=u["name"]))
        maintenance.validate(spec, u, o)
        objects.append(o)
    if fingerprint(objects) != req.get("expected_fingerprint"):
        raise ValueError("환경 상태가 변경되었습니다. 화면을 새로 열어 확인하세요.")
    if not lock_owned and not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    token = uuid.uuid4().hex[:12]
    folder = hotops.STATE / "maintenance"
    folder.mkdir(mode=0o700, exist_ok=True)
    record = dict(
        id=token,
        lab=lab,
        user="all",
        state="prepared",
        time=time.strftime("%Y-%m-%d %H:%M:%S"),
        originals=objects,
        gpu_indices=indices,
        changes=[],
    )
    journal = folder / (token + ".json")
    changes = record["changes"]
    active = False
    paused = False
    files = {}
    saved_policy = copy.deepcopy(c)
    policy_changed = False

    def state(s):
        record["state"] = s
        hotops.save(journal, record)

    api = ""
    try:
        state("prepared")
        api = "/v" + maintenance.engine("GET", "/version")["ApiVersion"]
        active = recovery.pause(spec)
        paused = True
        for o in objects:
            name = o["Name"].lstrip("/")
            retained = name + "-rollback-" + token
            item = dict(
                original=o["Id"], name=name, retained=retained, renamed=False, new=None
            )
            changes.append(item)
            state("recreating")
            if o["State"]["Running"]:
                maintenance.engine(
                    "POST", api + "/containers/" + o["Id"] + "/stop?t=15"
                )
            maintenance.engine(
                "POST",
                api
                + "/containers/"
                + o["Id"]
                + "/rename?name="
                + quote(retained, safe=""),
            )
            item["renamed"] = True
            state("original_retained")
            desired = payload(o, indices, devices)
            if not o["HostConfig"].get("ReadonlyRootfs"):
                snapshot = hotops.run(
                    "docker",
                    "commit",
                    o["Id"],
                    "labharbor-snapshot:" + token + "-" + str(len(changes)),
                    timeout=300,
                )
                item["snapshot_image"] = snapshot
                state("snapshot_saved")
                if not images:
                    desired["Image"] = snapshot
            if images:
                desired["Image"] = images[name]
                desired["Entrypoint"] = ["/usr/local/sbin/research-entrypoint"]
                desired["Cmd"] = []
                new_env = json.loads(
                    hotops.run("docker", "image", "inspect", images[name])
                )[0]["Config"].get("Env", [])
                merged = dict(
                    e.split("=", 1) for e in desired.get("Env", []) if "=" in e
                )
                merged.update(dict(e.split("=", 1) for e in new_env if "=" in e))
                merged["NVIDIA_VISIBLE_DEVICES"] = ",".join(devices)
                desired["Env"] = [k + "=" + v for k, v in merged.items()]
                desired["HostConfig"]["ReadonlyRootfs"] = not root_access
                desired["HostConfig"]["SecurityOpt"] = (
                    [] if root_access else ["no-new-privileges:true"]
                )
            item["new"] = maintenance.engine(
                "POST", api + "/containers/create?name=" + quote(name, safe=""), desired
            )["Id"]
            state("created")
            if o["State"]["Running"]:
                maintenance.engine(
                    "POST", api + "/containers/" + item["new"] + "/start"
                )
            now = hotops.obj(item["new"])
            if now["Image"] != desired["Image"] or maintenance.mount_signature(
                now
            ) != maintenance.mount_signature(o):
                raise ValueError("저장 연결 검증에 실패했습니다.")
            for key in [
                "DeviceRequests",
                "Devices",
                "PortBindings",
                "NanoCpus",
                "Memory",
                "MemorySwap",
                "ReadonlyRootfs",
            ]:
                if now["HostConfig"].get(key) != desired["HostConfig"].get(key):
                    raise ValueError("자원 설정 검증에 실패했습니다.")
            if o["State"]["Running"] and not now["State"]["Running"]:
                raise ValueError("새 환경이 시작되지 않았습니다.")
            if o["State"]["Running"] and (
                images
                or any(
                    e.startswith("RESEARCH_USER=") for e in o["Config"].get("Env", [])
                )
            ):
                for attempt in range(20):
                    try:
                        hotops.run(
                            "docker",
                            "exec",
                            item["new"],
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
                visible = hotops.run(
                    "docker",
                    "exec",
                    item["new"],
                    "nvidia-smi",
                    "--query-gpu=uuid",
                    "--format=csv,noheader",
                )
                if set(visible.splitlines()) != set(devices):
                    raise ValueError("GPU 격리 검증에 실패했습니다.")
        updated = [hotops.obj(item["new"]) for item in changes]
        c = hotops.cfg()
        s = c["labs"][lab]
        s.update(index=indices[0], indices=indices, gpu=devices[0], gpus=devices)
        if source_image:
            s.update(source_image=source_image, root_access=root_access)
        files = recovery.install(lab, s, updated)
        hotops.save(hotops.ETC / "policy.json", c)
        policy_changed = True
        recovery.resume(spec, active)
        state("complete")
        return {
            "message": "GPU 배정을 적용했습니다. 저장공간과 기존 개발환경은 유지됩니다."
        }
    except Exception:
        try:
            if policy_changed:
                hotops.save(hotops.ETC / "policy.json", saved_policy)
            if files:
                recovery.restore(files)
            for item, o in reversed(list(zip(changes, objects))):
                if item["new"]:
                    maintenance.engine(
                        "DELETE",
                        api + "/containers/" + item["new"] + "?force=true&v=false",
                    )
                if item["renamed"]:
                    maintenance.engine(
                        "POST",
                        api
                        + "/containers/"
                        + o["Id"]
                        + "/rename?name="
                        + quote(item["name"], safe=""),
                    )
                if (
                    o["State"]["Running"]
                    and not hotops.obj(o["Id"])["State"]["Running"]
                ):
                    maintenance.engine(
                        "POST", api + "/containers/" + o["Id"] + "/start"
                    )
            if paused:
                recovery.resume(spec, active)
            state("rolled_back")
        except Exception:
            state("recovery_required")
            raise ValueError(
                "자동 복구가 중단되었습니다. 관리자 확인이 필요합니다."
            ) from None
        raise ValueError("GPU 변경을 취소하고 이전 환경으로 복구했습니다.") from None
    finally:
        if not lock_owned:
            hotops.JOB_LOCK.release()


def submit(req):
    c = hotops.cfg()
    lab = req.get("lab")
    if lab not in c["labs"] or lab not in c["write_labs"]:
        raise PermissionError("등록된 관리 대상 연구실을 선택하세요.")
    if (
        req.get("confirm") != lab
        or req.get("ack_downtime") != "yes"
        or req.get("ack_recreate") != "yes"
    ):
        raise ValueError("대상 연구실과 작업 중단을 확인하세요.")
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    job = dict(
        id=uuid.uuid4().hex[:12],
        lab=lab,
        kind="gpu",
        state="queued",
        time=time.strftime("%Y-%m-%d %H:%M:%S"),
        message="GPU 배정 변경 대기 중",
    )
    (hotops.STATE / "jobs").mkdir(exist_ok=True)

    def worker():
        try:
            job.update(state="running", message="GPU 배정 변경 중")
            hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
            result = apply(req, lock_owned=True)
            job.update(state="complete", message=result["message"])
        except Exception as e:
            job.update(
                state="failed",
                message=str(e)
                if isinstance(e, (ValueError, PermissionError))
                else "GPU 배정 변경 중단. 복구 상태를 확인하세요.",
            )
        finally:
            hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
            hotops.JOB_LOCK.release()

    try:
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        __import__("threading").Thread(target=worker, daemon=True).start()
    except Exception:
        hotops.JOB_LOCK.release()
        raise
    return {"message": "GPU 배정 변경을 시작했습니다."}
