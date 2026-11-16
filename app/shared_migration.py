"""Explicit, reversible conversion of a single-account laboratory container."""
import copy
import pathlib
import time
import uuid
from urllib.parse import quote

import hotops
import maintenance
import recovery


def require_idle(spec):
    selected = set(spec.get("gpus", [spec["gpu"]]))
    raw = hotops.run("nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader,nounits")
    if any(row.split(",")[0].strip() in selected for row in raw.splitlines()):
        raise ValueError("GPU 실행 프로세스가 있어 전환을 중단했습니다. 작업 종료 후 다시 시도하세요.")
    raw = hotops.run("nvidia-smi", "--query-gpu=uuid,utilization.gpu,memory.used", "--format=csv,noheader,nounits")
    observed = set()
    for row in raw.splitlines():
        gpu, utilization, memory = [v.strip() for v in row.split(",")]
        if gpu in selected:
            observed.add(gpu)
            if int(utilization) > 0 or int(memory) > 32:
                raise ValueError("GPU 사용량이 감지되어 전환을 중단했습니다. 작업 종료 후 다시 시도하세요.")
    if observed != selected:
        raise ValueError("GPU 사용 상태를 확인할 수 없어 전환을 중단했습니다.")


def restart(req):
    c, spec, user, original = hotops.authorize(req)
    if req.get("ack_downtime") != "yes":
        raise ValueError("연구실 전체의 접속·실행 작업 종료를 확인하세요.")
    objects = {}
    for member in spec["users"]:
        _, _, _, obj = hotops.authorize(dict(req, user=member["name"]))
        objects[obj["Id"]] = obj
    import reconfigure
    if reconfigure.fingerprint(list(objects.values())) != req.get("expected_fingerprint"):
        raise ValueError("연구실 환경이 변경되었습니다. 화면을 새로 열어 확인하세요.")
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    paused = False
    active = False
    try:
        require_idle(spec)
        active = recovery.pause(spec)
        paused = True
        for obj in objects.values():
            hotops.run("docker", "restart", "--time", "15", obj["Id"], timeout=90)
            after = hotops.obj(obj["Id"])
            if not after["State"]["Running"] or maintenance.mount_signature(after) != maintenance.mount_signature(obj):
                raise ValueError("연구실 재시작 결과를 확인하세요.")
        return {"message": "연구실 환경을 재시작했습니다. 계정과 영구 저장 자료는 유지됩니다."}
    finally:
        try:
            if paused:
                recovery.resume(spec, active)
        finally:
            hotops.JOB_LOCK.release()


def apply(req):
    c, spec, user, original = hotops.authorize(req)
    if spec.get("account_layout") == "shared":
        return {"message": "이미 연구실 공용 컨테이너입니다."}
    if len(spec["users"]) != 1:
        raise ValueError("기존 다중 컨테이너 연구실은 계정·자료 이전 검토가 필요합니다. 자동으로 병합하지 않습니다.")
    if req.get("ack_downtime") != "yes" or req.get("ack_recreate") != "yes":
        raise ValueError("최초 전환 시 모든 접속·실행 작업 종료를 확인하세요.")
    if req.get("expected_id") != original["Id"][:12] or req.get("expected_started") != original["State"]["StartedAt"]:
        raise ValueError("환경 상태가 변경되었습니다. 화면을 새로 열어 확인하세요.")
    maintenance.validate(spec, user, original)
    require_idle(spec)
    if not original["HostConfig"].get("ReadonlyRootfs"):
        raise ValueError("쓰기 가능한 시스템 환경은 별도 스냅샷 이전이 필요합니다.")
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    root = pathlib.Path(spec["storage"])
    admin = root / ".admin/shared"
    name = hotops.name(spec, user)
    token = uuid.uuid4().hex[:12]
    retained = name + "-rollback-" + token
    record = dict(id=token, lab=req["lab"], user=user["name"], state="prepared", time=time.strftime("%Y-%m-%d %H:%M:%S"), original=original, old_name=retained)
    journal = hotops.STATE / "maintenance" / (token + ".json")
    journal.parent.mkdir(exist_ok=True, mode=0o700)
    renamed = False
    created = None
    active = False
    paused = False
    files = {}
    previous_policy = copy.deepcopy(c)
    policy_saved = False
    admin_created = False
    api = ""
    try:
        api = "/v" + maintenance.engine("GET", "/version")["ApiVersion"]
        hotops.save(journal, record)
        admin.mkdir(mode=0o700)
        admin_created = True
        for key in ("passwd", "group", "shadow", "gshadow"):
            content = hotops.run("docker", "exec", name, "cat", "/etc/" + key) + "\n"
            if key in ("group", "gshadow"):
                if any(line.startswith("orvia-research:") for line in content.splitlines()):
                    raise ValueError("연구실 그룹명이 이미 존재합니다.")
                gid = next(i for i in range(60001, 65000) if key != "group" or all(line.split(":")[2] != str(i) for line in content.splitlines()))
                content += (f"orvia-research:x:{gid}:{user['name']}\n" if key == "group" else f"orvia-research:!::{user['name']}\n")
            path = admin / key
            path.write_text(content)
            path.chmod(0o600 if key in ("shadow", "gshadow") else 0o644)
        entry = hotops.run("docker", "exec", name, "cat", "/usr/local/sbin/research-entrypoint")
        if "AllowUsers $RESEARCH_USER" not in entry:
            raise ValueError("SSH 시작 구성을 확인하세요.")
        (admin / "entrypoint.sh").write_text(entry.replace("AllowUsers $RESEARCH_USER", "AllowGroups orvia-research") + "\n")
        (admin / "entrypoint.sh").chmod(0o755)
        desired = maintenance.create_payload(original)
        desired["HostConfig"]["Binds"] = None
        desired["HostConfig"]["Mounts"] = [dict(Type="bind", Source=str(root), Target="/home", ReadOnly=False)] + [dict(Type="bind", Source=str(admin / key), Target="/etc/" + key, ReadOnly=True) for key in ("passwd", "group", "shadow", "gshadow")]
        desired["HostConfig"]["Mounts"] += [dict(Type="bind", Source=str(admin / "entrypoint.sh"), Target="/usr/local/sbin/research-entrypoint", ReadOnly=True)]
        desired["HostConfig"]["Mounts"] += [dict(Type="bind", Source=m["Source"], Target=m["Destination"], ReadOnly=not m["RW"]) for m in original["Mounts"] if m["Destination"] == "/etc/research-ssh"]
        require_idle(spec)
        active = recovery.pause(spec)
        paused = True
        maintenance.engine("POST", api + "/containers/" + original["Id"] + "/stop?t=15")
        maintenance.engine("POST", api + "/containers/" + original["Id"] + "/rename?name=" + quote(retained))
        renamed = True
        record["state"] = "original_retained"
        hotops.save(journal, record)
        created = maintenance.engine("POST", api + "/containers/create?name=" + quote(name), desired)["Id"]
        maintenance.engine("POST", api + "/containers/" + created + "/start")
        for attempt in range(20):
            try:
                hotops.run("docker", "exec", created, "/usr/sbin/sshd", "-t", "-f", "/run/sshd_config")
                break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(0.5)
        current = hotops.obj(created)
        if not current["State"]["Running"] or current["Image"] != original["Image"]:
            raise ValueError("공용 환경 검증 실패")
        spec["account_layout"] = "shared"
        spec["shared_container"] = name
        user["container"] = name
        from shared_accounts import validate_shared
        validate_shared(spec, current)
        files = recovery.install(req["lab"], spec, [current])
        hotops.save(hotops.ETC / "policy.json", c)
        policy_saved = True
        record["state"] = "complete"
        hotops.save(journal, record)
        return {"message": "연구실 공용 컨테이너로 전환했습니다. 기존 계정·자료·개발환경과 SSH 포트는 유지됩니다."}
    except Exception:
        if files:
            recovery.restore(files)
        if policy_saved:
            hotops.save(hotops.ETC / "policy.json", previous_policy)
        if created:
            maintenance.engine("DELETE", api + "/containers/" + created + "?force=true&v=false")
        if renamed:
            maintenance.engine("POST", api + "/containers/" + original["Id"] + "/rename?name=" + quote(name))
        if paused and original["State"]["Running"] and not hotops.obj(original["Id"])["State"]["Running"]:
            maintenance.engine("POST", api + "/containers/" + original["Id"] + "/start")
        if admin_created:
            admin.rename(admin.with_name("shared-failed-" + token))
        record["state"] = "rolled_back"
        hotops.save(journal, record)
        raise
    finally:
        try:
            if paused:
                recovery.resume(spec, active)
        finally:
            hotops.JOB_LOCK.release()
