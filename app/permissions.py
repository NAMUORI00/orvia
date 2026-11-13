"""Versioned policy profiles. Host administration is never delegated by a profile."""

import json
import pathlib
import re

CATALOG = json.loads(
    pathlib.Path(__file__)
    .with_name("permission_profiles.json")
    .read_text(encoding="utf-8")
)


def requested(req):
    key = req.get("permission_profile") or (
        "container_admin" if req.get("root_access") == "yes" else "standard"
    )
    if key not in CATALOG["profiles"]:
        raise ValueError("Unknown permission profile")
    profile = CATALOG["profiles"][key]
    if (
        CATALOG.get("schema_version") != 1
        or profile.get("host_docker") is not False
        or not isinstance(profile.get("container_sudo"), bool)
    ):
        raise ValueError("Unsupported permission profile capabilities")
    return key, profile


def account_sudo_rule(name, enabled):
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,30}", name):
        raise ValueError("Invalid account name")
    if not enabled:
        return ""
    return f"RUN command -v sudo >/dev/null && printf '%s\\n' '{name} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/research && chmod 440 /etc/sudoers.d/research\n"


def describe(spec, user, obj):
    config = obj["HostConfig"]
    elevated = bool(user.get("root_access", spec.get("root_access", False)))
    no_new = any(
        str(x).startswith("no-new-privileges") for x in config.get("SecurityOpt") or []
    )
    docker_mount = any(
        str(m.get("Destination", "")).endswith("docker.sock")
        for m in obj.get("Mounts", [])
    )
    unsafe = bool(
        config.get("Privileged") or config.get("PidMode") == "host" or docker_mount
    )
    mismatch = elevated and (config.get("ReadonlyRootfs") or no_new)
    return dict(
        schema_version=1,
        profile="container_admin" if elevated else "standard",
        container_sudo=elevated,
        workspace_packages=True,
        host_docker=False,
        readonly=bool(config.get("ReadonlyRootfs")),
        status="review" if unsafe or mismatch else "configured",
    )


def text(p, lang):
    if not p:
        return "N/A"
    if p.get("status") != "configured":
        return (
            "권한 설정 확인 필요"
            if lang == "ko"
            else "Permission configuration requires review"
        )
    if lang == "ko":
        return (
            "컨테이너 내부 sudo 허용. 시스템 패키지 설치 가능."
            if p["container_sudo"]
            else "일반 사용자. sudo 미제공."
        ) + " 사용자 작업공간의 패키지 설치 허용. 호스트 Docker 관리 권한 미제공."
    return (
        (
            "Container sudo permitted; system packages may be installed."
            if p["container_sudo"]
            else "Standard user; sudo is not provided."
        )
        + " Package installation in the user workspace is permitted. Host Docker administration is not provided."
    )
