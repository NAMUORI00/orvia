"""Account backup and deletion with retained, root-only recovery material."""
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time
import uuid

import hotops
import recovery
from shared_accounts import DATABASES, validate_shared, write_bound


def validate(req, spec, user, obj):
    deleting = req.get("action") == "account_delete"
    if deleting and (req.get("confirm_user") != user["name"] or req.get("ack_delete") != "yes"):
        raise ValueError("삭제할 계정 ID와 개인 자료 삭제를 확인하세요.")
    if deleting and len(spec["users"]) <= 1:
        raise ValueError("연구실의 마지막 계정은 삭제할 수 없습니다. 연구실 전체 정리는 별도 관리가 필요합니다.")
    root = pathlib.Path(spec["storage"]).resolve()
    home = root / user["name"]
    if not os.path.ismount(root) or home.is_symlink() or not home.is_dir() or home.resolve().parent != root:
        raise ValueError("개인 영구 저장 경로를 확인하세요.")
    if spec.get("account_layout") == "shared":
        validate_shared(spec, obj)
    elif not any(m["Destination"] == "/home/" + user["name"] and pathlib.Path(m["Source"]).resolve() == home for m in obj["Mounts"]):
        raise ValueError("계정의 저장 연결이 일치하지 않습니다.")
    if obj["State"]["Running"]:
        # UID is checked inside this container; no host process is signalled.
        rows = hotops.run("docker", "top", obj["Id"], "-eo", "uid,pid,comm").splitlines()[1:]
        if any(row.split()[0] == str(user["uid"]) for row in rows if row.split()):
            raise ValueError("이 계정의 접속 또는 실행 프로세스가 있습니다. 로그아웃·작업 종료 후 다시 시도하세요.")
    return root, home


def submit(req):
    c, spec, user, obj = hotops.authorize(req)
    validate(req, spec, user, obj)
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    job = dict(id=uuid.uuid4().hex[:12], lab=req["lab"], account=user["name"], kind="account", state="queued", time=time.strftime("%Y-%m-%d %H:%M:%S"), message="계정 백업 준비 중")
    try:
        (hotops.STATE / "jobs").mkdir(exist_ok=True)
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        threading.Thread(target=worker, args=(dict(req), job), daemon=True).start()
    except Exception:
        hotops.JOB_LOCK.release()
        raise
    return {"message": "계정 백업을 시작했습니다. 삭제 요청은 백업과 사용 상태 검증이 완료된 뒤 적용됩니다."}


def worker(req, job):
    originals = {}
    registered = True
    paused = False
    active = False
    files = {}
    try:
        c, spec, user, obj = hotops.authorize(req)
        root, home = validate(req, spec, user, obj)
        backup_root = root / ".admin/account-backups"
        backup_root.mkdir(mode=0o700, exist_ok=True)
        target = backup_root / (user["name"] + "-" + job["id"])
        target.mkdir(mode=0o700)
        needed = int(hotops.run("du", "-sb", str(home)).split()[0])
        if shutil.disk_usage(root).free < needed + 1024**3:
            raise ValueError("백업 공간이 부족합니다. 계정과 자료는 삭제하지 않았습니다.")
        job.update(state="running", message="개인 자료와 계정 복구 정보 백업 중")
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        archive = target / "home.tar"
        hotops.run("tar", "--sparse", "--acls", "--xattrs", "--numeric-owner", "--one-file-system", "-cf", str(archive), "-C", str(root), "--", user["name"], timeout=7200)
        archive.chmod(0o600)
        subprocess.run(["tar", "-tf", str(archive)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=300)
        hotops.save(target / "account.json", dict(lab=req["lab"], user=user, container=obj, scope="Personal home and account metadata; image layers are not included"))
        admin = root / ".admin" / ("shared" if spec.get("account_layout") == "shared" else user["name"])
        for key in DATABASES:
            source = admin / key
            if source.exists():
                originals[source] = source.read_text()
                (target / key).write_text(originals[source])
                (target / key).chmod(0o600)
        if req["action"] == "account_delete":
            # Check again after the potentially long backup, before any deletion.
            validate(req, spec, user, hotops.obj(obj["Id"]))
            registered = False
            if spec.get("account_layout") == "shared":
                for key in ("shadow", "passwd", "group", "gshadow"):
                    path = admin / key
                    rows = []
                    for line in originals[path].splitlines():
                        fields = line.split(":")
                        if fields[0] == user["name"]:
                            continue
                        if key in ("group", "gshadow"):
                            fields[3] = ",".join(n for n in fields[3].split(",") if n != user["name"])
                        rows.append(":".join(fields))
                    write_bound(path, "\n".join(rows) + "\n")
                # Authentication is now disabled. Refuse a session that raced the backup.
                validate(req, spec, user, hotops.obj(obj["Id"]))
            else:
                active = recovery.pause(spec)
                paused = True
                hotops.run("docker", "stop", "-t", "10", obj["Id"])
                # Retain the stopped container until policy and recovery updates succeed.
            spec["users"] = [u for u in spec["users"] if u["name"] != user["name"]]
            objects = {hotops.name(spec, u): hotops.obj(hotops.name(spec, u)) for u in spec["users"]}
            files = recovery.install(req["lab"], spec, list(objects.values()))
            hotops.save(hotops.ETC / "policy.json", c)
            registered = True
            if spec.get("account_layout") != "shared":
                hotops.run("docker", "rm", obj["Id"])
                shutil.move(str(admin), str(target / "legacy-admin"))
            # Only this validated account home is removed; the verified archive remains.
            shutil.rmtree(home)
            job.update(state="complete", message="계정과 개인 폴더 삭제 완료 · 복구 백업 보관", backup=str(target))
        else:
            job.update(state="complete", message="계정 백업 완료", backup=str(target))
    except Exception as error:
        if not registered:
            for path, text in originals.items():
                write_bound(path, text)
            if files:
                recovery.restore(files)
        job.update(state="failed", message=str(error) if isinstance(error, ValueError) else "계정 작업을 완료하지 못했습니다. 백업과 작업 기록을 확인하세요.")
    finally:
        try:
            if paused:
                recovery.resume(spec, active)
            hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        finally:
            hotops.JOB_LOCK.release()
