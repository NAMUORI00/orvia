"""Split a shared lab into per-user containers without moving personal data."""
import copy
import json
import os
import pathlib
import re
import shutil
import socket
import threading
import time
import uuid

import hotops
import lifecycle
import maintenance
import reconfigure
import recovery
from shared_accounts import DATABASES, validate_shared
from shared_migration import require_idle


def account_database(text, key, name, members):
    rows = []
    for line in text.splitlines():
        row = line.split(":")
        if row[0] in members and row[0] != name:
            continue
        if key in ("group", "gshadow"):
            row[3] = ",".join(x for x in row[3].split(",") if x not in members or x == name)
        if key == "shadow" and row[0] != name:
            row[1] = "!"
        rows.append(":".join(row))
    return "\n".join(rows) + "\n"


def validate(req):
    c, spec, user, obj = hotops.authorize(req)
    validate_shared(spec, obj)
    if req.get("ack_downtime") != "yes" or req.get("ack_recreate") != "yes":
        raise ValueError("접속 종료와 사용자별 컨테이너 전환을 확인하세요.")
    if reconfigure.fingerprint([obj]) != req.get("expected_fingerprint"):
        raise ValueError("환경 상태가 변경되었습니다. 화면을 새로 열어 확인하세요.")
    if len({hotops.name(spec, u) for u in spec["users"]}) != 1:
        raise ValueError("단일 공용 컨테이너에서만 분리할 수 있습니다.")
    if not obj["HostConfig"].get("ReadonlyRootfs"):
        raise ValueError("시스템 변경 내용이 있는 환경은 별도 스냅샷 이전이 필요합니다.")
    require_idle(spec)
    # Avoid interrupting an SSH/CPU job that began since the GPU check.
    uids = {str(u["uid"]) for u in spec["users"]}
    rows = hotops.run("docker", "top", obj["Id"], "-eo", "uid,pid,comm").splitlines()[1:]
    if any(row.split()[0] in uids for row in rows if row.split()):
        raise ValueError("접속 또는 사용자 실행 작업이 있습니다. 로그아웃·작업 종료 후 전환하세요.")
    return c, spec, user, obj


def submit(req):
    validate(req)
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    job = dict(id=uuid.uuid4().hex[:12], lab=req["lab"], kind="layout", state="queued", time=time.strftime("%Y-%m-%d %H:%M:%S"), message="사용자별 환경 준비 중")
    try:
        (hotops.STATE / "jobs").mkdir(exist_ok=True)
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        threading.Thread(target=worker, args=(dict(req), job), daemon=True).start()
    except Exception:
        hotops.JOB_LOCK.release()
        raise
    return {"message": "사용자별 컨테이너 전환을 시작했습니다. 개인 파일과 비밀번호는 유지됩니다."}


def worker(req, job):
    created = []
    files = {}
    renamed = False
    paused = False
    policy_saved = False
    api = ""
    try:
        c, spec, selected, original = validate(req)
        previous = copy.deepcopy(c)
        root = pathlib.Path(spec["storage"])
        token = job["id"]
        admin_root = root / ".admin" / ("separate-" + token)
        admin_root.mkdir(mode=0o700)
        hotops.save(admin_root / "policy-before.json", c)
        hotops.save(admin_root / "container-before.json", original)
        names = {u["name"] for u in spec["users"]}
        shared = root / ".admin/shared"
        databases = {key: (shared / key).read_text() for key in DATABASES}
        gid = int(next(row.split(":")[2] for row in databases["group"].splitlines() if row.startswith("orvia-research:")))
        common = root / "shared"
        if common.exists() or common.is_symlink():
            raise ValueError("공동 자료 폴더가 이미 있습니다. 연결 대상을 먼저 확인하세요.")
        common.mkdir(mode=0o2770)
        os.chown(common, 0, gid)
        common.chmod(0o2770)
        bind_ip = original["HostConfig"]["PortBindings"]["2222/tcp"][0].get("HostIp") or "0.0.0.0"
        reserved = {u["port"] for s in c["labs"].values() for u in s["users"]}
        prepared = []
        for i, user in enumerate(spec["users"]):
            name = user["name"]
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,30}", name):
                raise ValueError("계정 ID 형식을 확인하세요.")
            home = root / name
            if home.is_symlink() or home.stat().st_uid != user["uid"]:
                raise ValueError("개인 폴더 소유자와 경로를 확인하세요.")
            admin = admin_root / name
            admin.mkdir(mode=0o700)
            for key in DATABASES:
                path = admin / key
                path.write_text(account_database(databases[key], key, name, names))
                path.chmod(0o600 if key in ("shadow", "gshadow") else 0o644)
            entry = admin / "entrypoint.sh"
            entry.write_text(pathlib.Path(__file__).with_name("research-entrypoint.sh").read_text())
            entry.chmod(0o755)
            keys = admin / "ssh"
            if name == selected["name"]:
                old_keys = next(m["Source"] for m in original["Mounts"] if m["Destination"] == "/etc/research-ssh")
                shutil.copytree(old_keys, keys)
                port = selected["port"]
                container = original["Name"].lstrip("/")
            else:
                keys.mkdir(mode=0o700)
                hotops.run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "ssh_host_ed25519_key"))
                port = None
                for candidate in range(2201, 65000):
                    if candidate in reserved:
                        continue
                    with socket.socket() as probe:
                        try:
                            probe.bind((bind_ip, candidate))
                            port = candidate
                            break
                        except OSError:
                            continue
                if port is None:
                    raise ValueError("사용 가능한 SSH 포트가 없습니다.")
                container = "lh-" + req["lab"] + "-" + name
            reserved.add(port)
            net = "ov-" + token + "-" + str(i)
            bridge = "ov" + token[:8] + str(i)
            hotops.run("docker", "network", "create", "--driver", "bridge", "--label", "labharbor.lab=" + req["lab"], "--opt", "com.docker.network.bridge.name=" + bridge, "--opt", "com.docker.network.bridge.enable_icc=false", net)
            lifecycle.firewall(dict(uid=user["uid"], bridge=bridge, chain="OV" + token[:8] + str(i)))
            body = maintenance.create_payload(original)
            body.update(Hostname=container, WorkingDir="/home/" + name, Entrypoint=["/usr/local/sbin/research-entrypoint"], Cmd=[])
            body["Env"] = [e for e in body.get("Env", []) if e.split("=",1)[0] not in ("RESEARCH_USER","HOME","USER","LOGNAME")] + ["RESEARCH_USER=" + name,"HOME=/home/" + name,"USER=" + name,"LOGNAME=" + name]
            body["Labels"] = {**body.get("Labels", {}), "labharbor.lab": req["lab"], "orvia.account": name}
            h = body["HostConfig"]
            h["Binds"] = None
            h["Mounts"] = [dict(Type="bind", Source=str(home), Target="/home/" + name, ReadOnly=False),dict(Type="bind",Source=str(common),Target="/shared",ReadOnly=False)]
            h["Mounts"] += [dict(Type="bind",Source=str(admin/key),Target="/etc/"+key,ReadOnly=True) for key in DATABASES]
            h["Mounts"] += [dict(Type="bind",Source=str(entry),Target="/usr/local/sbin/research-entrypoint",ReadOnly=True),dict(Type="bind",Source=str(keys),Target="/etc/research-ssh",ReadOnly=True)]
            h["NetworkMode"] = net
            h["PortBindings"] = {"2222/tcp":[dict(HostIp=bind_ip,HostPort=str(port))]}
            body["NetworkingConfig"] = {"EndpointsConfig":{net:{}}}
            prepared.append((dict(user,container=container,port=port,credential_dir=str(admin.relative_to(root))),body))
        # No existing environment is stopped until all preparation is complete.
        validate(req)
        active = recovery.pause(spec)
        paused = True
        api = "/v" + maintenance.engine("GET", "/version")["ApiVersion"]
        old_name = original["Name"].lstrip("/")
        retained = old_name + "-rollback-" + token
        maintenance.engine("POST",api+"/containers/"+original["Id"]+"/stop?t=15")
        maintenance.engine("POST",api+"/containers/"+original["Id"]+"/rename?name="+retained)
        renamed = True
        for user, body in prepared:
            job.update(state="running",message="사용자별 환경 시작: " + user["name"])
            hotops.save(hotops.STATE/"jobs"/(token+".json"),job)
            new = maintenance.engine("POST",api+"/containers/create?name="+user["container"],body)["Id"]
            created.append(new)
            maintenance.engine("POST",api+"/containers/"+new+"/start")
            for attempt in range(20):
                try:
                    hotops.run("docker","exec",new,"/usr/sbin/sshd","-t","-f","/run/sshd_config")
                    break
                except Exception:
                    if attempt==19: raise
                    time.sleep(0.5)
            visible = hotops.run("docker","exec","--user",str(user["uid"]),new,"nvidia-smi","--query-gpu=uuid","--format=csv,noheader")
            if set(visible.splitlines()) != set(spec.get("gpus",[spec["gpu"]])):
                raise ValueError("GPU 격리 검증 실패")
            after = hotops.obj(new)
            if not after["State"]["Running"] or after["Image"] != original["Image"]:
                raise ValueError("개발환경 검증 실패")
        spec["users"] = [u for u, _ in prepared]
        spec["account_layout"] = "separate"
        spec["shared_folder"] = str(common)
        spec["shared_gid"] = gid
        spec.pop("shared_container",None)
        files = recovery.install(req["lab"],spec,[hotops.obj(n) for n in created])
        latest = hotops.cfg()
        if latest["labs"][req["lab"]] != previous["labs"][req["lab"]]:
            raise ValueError("연구실 설정이 변경되어 이전 환경으로 복구합니다.")
        latest["labs"][req["lab"]] = spec
        hotops.save(hotops.ETC/"policy.json",latest)
        policy_saved = True
        job.update(state="complete",message="사용자별 컨테이너 전환 완료 · 개인 자료와 비밀번호 유지",ports={u["name"]:u["port"] for u,_ in prepared},retained=retained)
    except Exception as error:
        if files: recovery.restore(files)
        if policy_saved:
            latest = hotops.cfg()
            latest["labs"][req["lab"]] = previous["labs"][req["lab"]]
            hotops.save(hotops.ETC/"policy.json",latest)
        for new in reversed(created):
            maintenance.engine("DELETE",api+"/containers/"+new+"?force=true&v=false")
        if renamed:
            maintenance.engine("POST",api+"/containers/"+original["Id"]+"/rename?name="+old_name)
        if paused and not hotops.obj(original["Id"])["State"]["Running"]:
            maintenance.engine("POST",api+"/containers/"+original["Id"]+"/start")
        job.update(state="failed",message=str(error) if isinstance(error,ValueError) else "분리 실패 · 기존 환경 복구 상태를 확인하세요.")
    finally:
        try:
            if paused: recovery.resume(spec,active)
            hotops.save(hotops.STATE/"jobs"/(job["id"]+".json"),job)
        finally:
            hotops.JOB_LOCK.release()
