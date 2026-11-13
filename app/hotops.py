"""Non-recreating controls for registered containers; imported production policy remains authoritative."""

import concurrent.futures, hashlib, json, os, pathlib, re, socket, subprocess, threading, time

ETC = pathlib.Path("/etc/h200-console")
STATE = pathlib.Path("/var/lib/h200-console")
JOB_LOCK = threading.Lock()


def run(*args, timeout=120, input=None):
    return subprocess.check_output(
        args, input=input, text=True, stderr=subprocess.PIPE, timeout=timeout
    ).strip()


def cfg():
    return json.loads((ETC / "policy.json").read_text())


def save(p, obj):
    p = pathlib.Path(p)
    t = p.with_suffix(".next")
    t.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    t.chmod(0o600)
    t.replace(p)


def name(s, u):
    return u.get("container", s["prefix"] + u["name"])


def obj(n):
    return json.loads(run("docker", "inspect", n))[0]


def authorize(req):
    c = cfg()
    lab = req.get("lab")
    s = c["labs"].get(lab)
    if not s or lab not in c["write_labs"]:
        raise PermissionError("이 연구실은 현재 변경 보호 대상입니다.")
    if req.get("confirm") != lab:
        raise ValueError("연구실 ID를 입력하여 확인하세요.")
    u = next((u for u in s["users"] if u["name"] == req.get("user")), None)
    if u is None:
        raise ValueError("계정을 선택하세요.")
    o = obj(name(s, u))
    requests = o["HostConfig"].get("DeviceRequests") or []
    selected = [g for r in requests for g in (r.get("DeviceIDs") or [])]
    if (
        not selected
        or any(g not in c["write_gpus"] for g in selected)
        or any(r.get("Count") == -1 for r in requests)
    ):
        raise PermissionError("변경 허용 범위 밖의 GPU입니다.")
    if o["HostConfig"]["Privileged"] or o["HostConfig"]["NetworkMode"] == "host":
        raise PermissionError("격리 설정을 확인하세요.")
    return c, s, u, o


def catalog():
    c = cfg()
    result = []
    ids = run("docker", "ps", "-aq").split()
    all_objects = json.loads(run("docker", "inspect", *ids)) if ids else []
    lookup = {o["Name"].lstrip("/"): o for o in all_objects}
    for key, s in c["labs"].items():
        users = []
        for u in s["users"]:
            o = lookup.get(name(s, u))
            if not o:
                continue
            h = o["HostConfig"]
            users.append(
                dict(
                    name=u["name"],
                    profile=__import__("account_profile").public(u),
                    container=name(s, u),
                    cpu=h.get("NanoCpus", 0) / 1e9 or None,
                    ram=h.get("Memory", 0) / 1073741824 or None,
                    image=o["Config"]["Image"],
                    readonly=h.get("ReadonlyRootfs", False),
                    id=o["Id"][:12],
                    started=o["State"]["StartedAt"],
                    root_access=not h.get("ReadonlyRootfs", False),
                )
            )
        result.append(
            dict(
                id=key,
                title=s["title"],
                users=users,
                writable=key in c["write_labs"],
                fingerprint=__import__("reconfigure").fingerprint(
                    [lookup[name(s, u)] for u in s["users"] if name(s, u) in lookup]
                ),
            )
        )
    jobs = []
    for p in sorted(
        (STATE / "jobs").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )[:20]:
        j = json.loads(p.read_text())
        if j.get("state") in {"running", "queued"} and not JOB_LOCK.locked():
            j.update(
                state="interrupted",
                message="백업 작업이 중단되었습니다. 기존 파일을 확인하세요.",
            )
            save(p, j)
        jobs.append(j)
    drafts = (
        json.loads((STATE / "profiles.json").read_text())
        if (STATE / "profiles.json").exists()
        else {}
    )
    known = {u["container"] for l in result for u in l["users"]}
    available = []
    for o in all_objects:
        n = o["Name"].lstrip("/")
        if n not in known and "-rollback-" not in n:
            available.append(
                dict(
                    name=n,
                    image=o["Config"]["Image"],
                    mounts=[
                        m["Source"]
                        for m in o["Mounts"]
                        if m["Type"] == "bind" and pathlib.Path(m["Source"]).is_dir()
                    ],
                )
            )
    maintenance = []
    for path in sorted(
        (STATE / "maintenance").glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:20]:
        record = json.loads(path.read_text())
        maintenance.append(
            {k: record.get(k) for k in ["id", "lab", "user", "state", "time"]}
        )
    return dict(
        maintenance=maintenance,
        labs=result,
        jobs=jobs,
        profiles=drafts,
        available=available,
        storage_limit=c.get("max_storage_gb", 100),
    )


def dispatch(req):
    if req.get("action") == "environment_apply":
        return __import__("environments").submit(req)

    if req.get("action") == "account_create":
        return __import__("accounts").submit(req)

    if req.get("action") == "gpu_reconfigure":
        return __import__("reconfigure").submit(req)

    if req.get("action") == "account_metadata":
        c, s, u, o = authorize(req)
        import account_profile

        profile = account_profile.clean(req)
        u["profile"] = {**u.get("profile", {}), **profile}
        save(ETC / "policy.json", c)
        return {"message": "계정 정보를 저장했습니다."}

    if req.get("action") == "metadata":
        c = cfg()
        lab = req.get("lab")
        spec = c["labs"].get(lab)
        if not spec or lab not in c["write_labs"] or spec["gpu"] not in c["write_gpus"]:
            raise PermissionError("이 연구실은 현재 변경 보호 대상입니다.")
        title = str(req.get("title") or "").strip()
        if (
            req.get("confirm") != lab
            or not 1 <= len(title) <= 100
            or any(ord(ch) < 32 for ch in title)
        ):
            raise ValueError("연구실 이름과 대상을 확인하세요.")
        spec["title"] = title
        save(ETC / "policy.json", c)
        return {
            "message": "연구실 이름을 저장했습니다. 사용자와 실행 작업은 유지됩니다."
        }
    if req.get("action") == "register":
        return register(req)
    if req.get("action") == "profile_save":
        lab = req.get("lab")
        c = cfg()
        if lab not in c["labs"]:
            raise ValueError("등록된 연구실을 선택하세요.")
        if req.get("image_provider") not in {"cuda", "pytorch"} or not re.fullmatch(
            "[A-Za-z0-9_.-]{1,100}", req.get("image_tag", "")
        ):
            raise ValueError("공식 이미지 태그를 선택하세요.")
        item = {
            k: req.get(k)
            for k in [
                "image_provider",
                "image_tag",
                "cpu",
                "ram",
                "storage",
                "root_access",
                "gpu_selection",
            ]
        }
        p = STATE / "profiles.json"
        profiles = json.loads(p.read_text()) if p.exists() else {}
        profiles[lab] = item
        save(p, profiles)
        return {"message": "프리셋을 저장했습니다. 실행 환경은 변경하지 않았습니다."}
    c, s, u, o = authorize(req)
    if req["action"] == "maintenance_recreate":
        import maintenance

        return maintenance.recreate(req, c, s, u, o)
    if req["action"] == "maintenance_restart":
        if req.get("ack_downtime") != "yes":
            raise ValueError("실행 작업 중단을 확인해야 재시작할 수 있습니다.")
        if (
            req.get("expected_id") != o["Id"][:12]
            or req.get("expected_started") != o["State"]["StartedAt"]
        ):
            raise ValueError("환경 상태가 변경되었습니다. 화면을 새로 열어 확인하세요.")
        if not JOB_LOCK.acquire(blocking=False):
            raise ValueError("다른 관리 작업이 진행 중입니다. 완료 후 다시 시도하세요.")
        try:
            run("docker", "restart", "--time", "15", name(s, u), timeout=90)
            after = obj(name(s, u))
            if (
                after["Id"] != o["Id"]
                or after["Mounts"] != o["Mounts"]
                or not after["State"]["Running"]
            ):
                raise ValueError(
                    "재시작 후 상태 확인이 필요합니다. 작업 기록을 확인하세요."
                )
            return {
                "message": "선택한 사용자 환경을 재시작했습니다. 저장 경로는 유지됩니다."
            }
        finally:
            JOB_LOCK.release()
    if req["action"] == "resources":
        cpu = float(req.get("cpu", 0))
        ram = int(req.get("ram", 0))
        total = (
            int(
                next(
                    l.split()[1]
                    for l in pathlib.Path("/proc/meminfo").read_text().splitlines()
                    if l.startswith("MemTotal:")
                )
            )
            // 1048576
        )
        if not (cpu == 0 or 0.25 <= cpu <= os.cpu_count()) or not (
            ram == 0 or 1 <= ram <= total
        ):
            raise ValueError("자원 한도를 확인하세요.")
        oldram = o["HostConfig"].get("Memory", 0)
        releasing = (
            cpu == 0
            and (
                o["HostConfig"].get("NanoCpus", 0)
                or o["HostConfig"].get("CpuQuota", 0) > 0
            )
        ) or (ram == 0 and oldram > 0)
        if releasing:
            if req.get("ack_downtime") != "yes":
                raise ValueError(
                    "자원 한도 해제에는 사용자 환경 재생성 확인이 필요합니다."
                )
            import maintenance

            approved = dict(
                req,
                ack_recreate="yes",
                expected_id=o["Id"][:12],
                expected_started=o["State"]["StartedAt"],
            )
            maintenance.recreate(
                approved,
                c,
                s,
                u,
                o,
                resource_limits=dict(
                    NanoCpus=int(cpu * 1e9),
                    CpuQuota=0,
                    CpuPeriod=0,
                    Memory=ram * 1073741824,
                    MemorySwap=ram * 1073741824 if ram else -1,
                ),
            )
            return {"message": "CPU·메모리 한도를 적용했습니다."}
        shrinking = bool(
            o["State"]["Running"] and ram and (oldram == 0 or ram * 1073741824 < oldram)
        )
        if shrinking and req.get("ack_downtime") != "yes":
            raise ValueError(
                "메모리 한도 축소에는 사용자 환경 재시작 확인이 필요합니다."
            )
        if not JOB_LOCK.acquire(blocking=False):
            raise ValueError("다른 관리 작업이 진행 중입니다.")
        import recovery

        active = False
        paused = False
        stopped = False

        def limits(cpus, memory, swap):
            run(
                "docker",
                "update",
                "--cpus",
                str(cpus),
                "--memory",
                str(memory),
                "--memory-swap",
                str(swap),
                name(s, u),
            )

        try:
            if shrinking:
                active = recovery.pause(s)
                paused = True
                run("docker", "stop", "-t", "15", name(s, u))
                stopped = True
            limits(cpu, ram * 1073741824, ram * 1073741824 if ram else -1)
            if stopped:
                run("docker", "start", name(s, u))
            after = obj(name(s, u))
            if after["Id"] != o["Id"] or __import__("maintenance").mount_signature(
                after
            ) != __import__("maintenance").mount_signature(o):
                raise ValueError("환경 상태가 변경되었습니다.")
            if not shrinking and after["State"]["StartedAt"] != o["State"]["StartedAt"]:
                raise ValueError("환경 실행 상태가 변경되었습니다.")
            return {"message": "CPU·메모리 한도를 적용했습니다."}
        except Exception:
            if stopped:
                if obj(name(s, u))["State"]["Running"]:
                    run("docker", "stop", "-t", "15", name(s, u))
                limits(
                    o["HostConfig"].get("NanoCpus", 0) / 1e9,
                    oldram,
                    o["HostConfig"].get("MemorySwap", 0),
                )
                run("docker", "start", name(s, u))
            raise
        finally:
            try:
                if paused:
                    recovery.resume(s, active)
            finally:
                JOB_LOCK.release()
    if req["action"] == "adduser":
        if o["HostConfig"]["ReadonlyRootfs"]:
            raise ValueError(
                "읽기 전용 계정 환경입니다. 재생성 없이 계정을 추가할 수 없습니다."
            )
        new = req.get("new_user", "")
        password = req.get("password", "")
        if (
            not re.fullmatch("[a-z][a-z0-9_-]{2,30}", new)
            or not 10 <= len(password) <= 128
            or "\n" in password
        ):
            raise ValueError("새 계정과 비밀번호를 확인하세요.")
        # Home must already be a persistent mount; never silently place new data in a disposable layer.
        if not any(m["Destination"] == "/home" and m["RW"] for m in o["Mounts"]):
            raise ValueError(
                "영구 /home 마운트가 있는 컨테이너에서만 계정을 추가할 수 있습니다."
            )
        # A restricted SSH AllowUsers rule would silently prevent new login; do not rewrite it.
        ssh = run("docker", "exec", "--user", "0", name(s, u), "/usr/sbin/sshd", "-T")
        if any(
            l.startswith(("allowusers ", "denyusers ", "allowgroups ", "denygroups "))
            for l in ssh.splitlines()
        ):
            raise ValueError(
                "SSH 계정 허용 목록이 설정되어 있습니다. 별도 검토 없이 변경하지 않습니다."
            )
        test = subprocess.run(
            ["docker", "exec", name(s, u), "id", new], capture_output=True
        )
        if test.returncode == 0:
            raise ValueError("이미 존재하는 계정입니다.")
        run(
            "docker",
            "exec",
            "--user",
            "0",
            name(s, u),
            "useradd",
            "--create-home",
            "--shell",
            "/bin/bash",
            new,
        )
        try:
            run(
                "docker",
                "exec",
                "--user",
                "0",
                "-i",
                name(s, u),
                "chpasswd",
                input=new + ":" + password + "\n",
            )
        except Exception:
            run("docker", "exec", "--user", "0", name(s, u), "usermod", "--lock", new)
            raise ValueError("비밀번호 설정 실패. 새 계정은 잠금 상태입니다.")
        uid = int(run("docker", "exec", name(s, u), "id", "-u", new))
        c = cfg()
        c["labs"][req["lab"]]["users"].append(
            dict(name=new, container=name(s, u), port=u["port"], uid=uid)
        )
        save(ETC / "policy.json", c)
        return {"message": "컨테이너 내부 계정을 추가했습니다. 기존 계정은 유지됩니다."}
    if req["action"] == "backup":
        if req.get("consistency") != "live":
            raise ValueError("무중단 파일 백업 확인이 필요합니다.")
        if not JOB_LOCK.acquire(blocking=False):
            raise ValueError("백업이 이미 진행 중입니다.")
        job = dict(
            id=os.urandom(8).hex(),
            lab=req["lab"],
            state="queued",
            message="백업 대기 중",
            time=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        (STATE / "jobs").mkdir(exist_ok=True)
        save(STATE / "jobs" / (job["id"] + ".json"), job)
        threading.Thread(target=backup, args=(c, s, job), daemon=True).start()
        return {"message": "연구실 백업을 시작했습니다. 컨테이너를 중지하지 않습니다."}
    raise ValueError("지원하지 않는 작업입니다.")


def backup(c, s, job):
    try:
        members = [(u, obj(name(s, u))) for u in s["users"]]
        for u, o in members:
            authorize(dict(lab=job["lab"], user=u["name"], confirm=job["lab"]))
        root = pathlib.Path(c.get("backup_root", "/var/lib/labharbor/backups"))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = root / (job["lab"] + "-" + job["id"])
        target.mkdir(mode=0o700)
        mounts = {
            m["Source"] for _, o in members for m in o["Mounts"] if m["Type"] == "bind"
        }
        allowed = pathlib.Path(s["storage"]).resolve()
        if any(not pathlib.Path(m).resolve().is_relative_to(allowed) for m in mounts):
            raise ValueError("백업 범위를 벗어난 마운트입니다.")
        need = sum(int(run("du", "-sb", p).split()[0]) for p in mounts) + sum(
            int(json.loads(run("docker", "image", "inspect", o["Image"]))[0]["Size"])
            for _, o in members
        )
        st = os.statvfs(root)
        if st.f_bavail * st.f_frsize < need + 5 * 10**9:
            raise ValueError("백업 공간이 부족합니다.")
        job.update(state="running", message="무중단 파일 백업 중")
        save(STATE / "jobs" / (job["id"] + ".json"), job)
        metadata = dict(profile=s, consistency="live-best-effort", containers=[])
        for u, o in members:
            n = name(s, u)
            run(
                "docker",
                "export",
                "-o",
                str(target / (u["name"] + "-rootfs.tar")),
                n,
                timeout=7200,
            )
            metadata["containers"].append(dict(user=u, inspect=o))
        run(
            "tar",
            "--sparse",
            "--acls",
            "--xattrs",
            "--numeric-owner",
            "-cf",
            str(target / "persistent-data.tar"),
            "-C",
            str(allowed),
            ".",
            timeout=7200,
        )
        save(target / "metadata.json", metadata)
        manifest = {}
        for p in target.iterdir():
            h = hashlib.sha256()
            with p.open("rb") as f:
                for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
                    h.update(b)
            manifest[p.name] = h.hexdigest()
        save(target / "manifest.json", manifest)
        job.update(state="complete", message="백업 완료", path=str(target))
    except Exception as e:
        job.update(
            state="failed",
            message=str(e)
            if isinstance(e, ValueError)
            else "백업 실패. 진행 중인 파일 변경 또는 저장공간을 확인하세요.",
        )
    finally:
        save(STATE / "jobs" / (job["id"] + ".json"), job)
        JOB_LOCK.release()


def register(req):
    c = cfg()
    key = req.get("id", "")
    n = req.get("container", "")
    if not re.fullmatch("[a-z][a-z0-9-]{2,23}", key) or key in c["labs"]:
        raise ValueError("새 연구실 ID를 확인하세요.")
    available = catalog()["available"]
    entry = next((x for x in available if x["name"] == n), None)
    if not entry or req.get("storage") not in entry["mounts"]:
        raise ValueError("등록 가능한 컨테이너와 저장경로를 선택하세요.")
    username = req.get("username", "")
    if not re.fullmatch("[A-Za-z][A-Za-z0-9_-]{1,31}", username):
        raise ValueError("기존 계정 ID를 입력하세요.")
    o = obj(n)
    requests = o["HostConfig"].get("DeviceRequests") or []
    gpus = [g for r in requests for g in r.get("DeviceIDs", [])]
    known = {
        b.strip(): int(a)
        for a, b in (
            l.split(",")
            for l in run(
                "nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"
            ).splitlines()
        )
    }
    if len(gpus) != 1 or gpus[0] not in known:
        raise ValueError(
            "현재 버전은 GPU UUID가 명시된 단일 GPU 환경을 등록할 수 있습니다."
        )
    ports = [
        int(p["HostPort"])
        for v in (o["HostConfig"].get("PortBindings") or {}).values()
        for p in (v or [])
    ]
    port = int(req.get("port", 0))
    if port not in ports:
        raise ValueError("컨테이너에 공개된 실제 SSH 포트를 입력하세요.")
    c["labs"][key] = dict(
        title=str(req.get("title", ""))[:100] or key,
        index=known[gpus[0]],
        gpu=gpus[0],
        users=[dict(name=username, container=n, port=port, uid=0)],
        storage=req["storage"],
        prefix="",
        imported=True,
        sandbox=False,
    )
    # Registration is metadata-only. Explicit installation policy determines whether hot controls are enabled.
    if gpus[0] in c["write_gpus"]:
        c["write_labs"].append(key)
    save(ETC / "policy.json", c)
    return {
        "message": "기존 환경을 연구실로 등록했습니다. 컨테이너는 변경하지 않았습니다."
    }


def build_source(image):
    """BuildKit treats FROM sha256:... as a registry tag; pin a local alias."""
    digest = json.loads(run("docker", "image", "inspect", image))[0]["Id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid source image digest")
    alias = "labharbor-base:" + digest.split(":", 1)[1]
    run("docker", "image", "tag", digest, alias)
    return alias
