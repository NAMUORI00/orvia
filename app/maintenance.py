"""Recreate a managed read-only environment from its existing immutable image.

Persistent bind mounts are never moved, formatted or deleted. Writable roots,
anonymous volumes, shared account containers and static addresses are excluded.
"""

import copy
import http.client
import json
import os
import pathlib
import re
import socket
import subprocess
import time
import uuid
from urllib.parse import quote

import hotops


class EngineConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def engine(method, path, payload=None):
    connection = EngineConnection("localhost", timeout=90)
    try:
        connection.request(
            method,
            path,
            body=json.dumps(payload) if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read()
        if not 200 <= response.status < 300:
            raise ValueError(
                "환경 관리 명령이 실패했습니다. 이전 환경 복구 상태를 확인하세요."
            )
        return json.loads(raw) if raw else {}
    finally:
        connection.close()


def mount_signature(o):
    return sorted(
        (m["Type"], m["Source"], m["Destination"], bool(m["RW"])) for m in o["Mounts"]
    )


def validate(spec, user, o):
    if not spec.get("managed") or not o["HostConfig"].get("ReadonlyRootfs"):
        raise ValueError(
            "현재 기능은 관리형 읽기 전용 환경의 동일 구성 재생성만 지원합니다."
        )
    if sum(hotops.name(spec, u) == hotops.name(spec, user) for u in spec["users"]) != 1:
        raise ValueError("여러 사용자가 공유하는 환경은 별도 이전이 필요합니다.")
    storage = pathlib.Path(spec["storage"]).resolve()
    if not os.path.ismount(storage):
        raise ValueError("영구 저장공간 연결을 확인하세요.")
    if not o["Mounts"] or any(
        m["Type"] != "bind"
        or not pathlib.Path(m["Source"]).exists()
        or not pathlib.Path(m["Source"]).resolve().is_relative_to(storage)
        for m in o["Mounts"]
    ):
        raise ValueError("저장 경로가 확인되지 않아 재생성을 중단했습니다.")
    if o["HostConfig"].get("VolumesFrom") or o["HostConfig"].get("AutoRemove"):
        raise ValueError("현재 환경의 저장 설정은 재생성을 지원하지 않습니다.")
    if any(n.get("IPAMConfig") for n in o["NetworkSettings"]["Networks"].values()):
        raise ValueError("고정 네트워크 환경은 별도 이전이 필요합니다.")
    if not re.fullmatch(r"labharbor-[a-z][a-z0-9-]*\.service", spec.get("service", "")):
        raise ValueError("연결된 복구 서비스를 확인하세요.")


def create_payload(o):
    allowed = {
        "Hostname",
        "Domainname",
        "User",
        "AttachStdin",
        "AttachStdout",
        "AttachStderr",
        "ExposedPorts",
        "Tty",
        "OpenStdin",
        "StdinOnce",
        "Env",
        "Cmd",
        "Healthcheck",
        "Image",
        "Volumes",
        "WorkingDir",
        "Entrypoint",
        "NetworkDisabled",
        "Labels",
        "StopSignal",
        "StopTimeout",
        "Shell",
    }
    payload = {
        k: copy.deepcopy(v)
        for k, v in o["Config"].items()
        if k in allowed and v is not None
    }
    payload["Image"] = o["Image"]
    payload["HostConfig"] = copy.deepcopy(o["HostConfig"])
    networks = {}
    for name, config in o["NetworkSettings"]["Networks"].items():
        networks[name] = {
            "Aliases": [
                a
                for a in (config.get("Aliases") or [])
                if a not in (o["Id"], o["Id"][:12])
            ]
        }
    payload["NetworkingConfig"] = {"EndpointsConfig": networks}
    return payload


def recreate(req, c, spec, user, original):
    if req.get("ack_downtime") != "yes" or req.get("ack_recreate") != "yes":
        raise ValueError("작업 중단과 동일 구성 재생성을 모두 확인해야 합니다.")
    if (
        req.get("expected_id") != original["Id"][:12]
        or req.get("expected_started") != original["State"]["StartedAt"]
    ):
        raise ValueError("환경 상태가 변경되었습니다. 화면을 새로 열어 확인하세요.")
    validate(spec, user, original)
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다. 완료 후 다시 시도하세요.")
    name = hotops.name(spec, user)
    token = uuid.uuid4().hex[:12]
    old_name = name + "-rollback-" + token
    service = spec["service"]
    timer = service.removesuffix(".service") + ".timer"
    timer_active = (
        subprocess.run(["systemctl", "is-active", "--quiet", timer]).returncode == 0
    )
    folder = hotops.STATE / "maintenance"
    folder.mkdir(mode=0o700, exist_ok=True)
    record = dict(
        id=token,
        lab=req["lab"],
        user=user["name"],
        state="prepared",
        original=original,
        old_name=old_name,
        name=name,
        time=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    path = folder / (token + ".json")
    renamed = False
    created_id = None
    api = ""

    def state(value):
        record["state"] = value
        hotops.save(path, record)

    try:
        state("prepared")
        version = engine("GET", "/version")["ApiVersion"]
        if not re.fullmatch(r"1\.\d+", version):
            raise ValueError("Docker API 버전을 확인하세요.")
        api = "/v" + version
        hotops.run("systemctl", "stop", timer, service)
        if original["State"]["Running"]:
            engine("POST", api + "/containers/" + original["Id"] + "/stop?t=15")
        engine(
            "POST",
            api
            + "/containers/"
            + original["Id"]
            + "/rename?name="
            + quote(old_name, safe=""),
        )
        renamed = True
        state("original_retained")
        result = engine(
            "POST",
            api + "/containers/create?name=" + quote(name, safe=""),
            create_payload(original),
        )
        created_id = result["Id"]
        record["created_id"] = created_id
        state("created")
        if original["State"]["Running"]:
            engine("POST", api + "/containers/" + created_id + "/start")
        current = hotops.obj(created_id)
        if current["Image"] != original["Image"] or mount_signature(
            current
        ) != mount_signature(original):
            raise ValueError("개발환경 또는 저장 연결 검증에 실패했습니다.")
        for key in [
            "DeviceRequests",
            "PortBindings",
            "NanoCpus",
            "Memory",
            "MemorySwap",
            "ReadonlyRootfs",
            "Devices",
        ]:
            if current["HostConfig"].get(key) != original["HostConfig"].get(key):
                raise ValueError("자원 설정 검증에 실패했습니다.")
        if original["State"]["Running"]:
            for attempt in range(20):
                current = hotops.obj(created_id)
                if not current["State"]["Running"]:
                    raise ValueError("새 환경이 정상 실행되지 않았습니다.")
                try:
                    if any(
                        e.startswith("RESEARCH_USER=")
                        for e in original["Config"].get("Env", [])
                    ):
                        hotops.run(
                            "docker",
                            "exec",
                            created_id,
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
        state("verified")
        # The old container is retained stopped for administrator recovery; its
        # immutable image and persistent binds are also recorded in the journal.
        if timer_active:
            hotops.run("systemctl", "start", timer)
        state("complete")
        return {
            "message": "동일 구성으로 재생성했습니다. 저장 파일과 개발환경은 유지됩니다."
        }
    except Exception:
        try:
            if created_id:
                engine(
                    "DELETE", api + "/containers/" + created_id + "?force=true&v=false"
                )
            if renamed:
                engine(
                    "POST",
                    api
                    + "/containers/"
                    + original["Id"]
                    + "/rename?name="
                    + quote(name, safe=""),
                )
            if (
                api
                and original["State"]["Running"]
                and not hotops.obj(original["Id"])["State"]["Running"]
            ):
                engine("POST", api + "/containers/" + original["Id"] + "/start")
            if timer_active:
                hotops.run("systemctl", "start", timer)
            state("rolled_back")
        except Exception:
            state("recovery_required")
            raise ValueError(
                "재생성 및 자동 복구가 중단되었습니다. 관리자 복구가 필요합니다."
            ) from None
        raise ValueError("재생성을 취소하고 이전 환경으로 복구했습니다.") from None
    finally:
        hotops.JOB_LOCK.release()
