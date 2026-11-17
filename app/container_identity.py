"""Rename registered containers without restarting research processes."""
import copy
import re
import hotops
import recovery


def replace_name(value, old, new):
    if isinstance(value, dict):
        return {k: replace_name(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_name(v, old, new) for v in value]
    return new if value == old else value


def rename(req):
    new = str(req.get("container_name") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", new):
        raise ValueError("컨테이너 이름은 영문·숫자·점·밑줄·하이픈으로 입력하세요.")
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    paused = False
    renamed = False
    try:
        c, spec, user, before = hotops.authorize(req)
        if req.get("expected_id") != before["Id"][:12] or req.get("expected_started") != before["State"]["StartedAt"]:
            raise ValueError("환경 상태가 변경되었습니다. 새로고침 후 다시 확인하세요.")
        old = hotops.name(spec, user)
        if new == old:
            return {"message": "현재 이름과 같습니다."}
        existing = hotops.run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
        if new in existing:
            raise ValueError("이미 사용 중인 컨테이너 이름입니다.")
        path = recovery.recovery_path(req["lab"])
        if not path.exists():
            raise ValueError("자동복구 설정을 먼저 확인하세요.")
        import json
        record = json.loads(path.read_text())
        if old not in [x["name"] for x in record["containers"]]:
            raise ValueError("자동복구 대상이 일치하지 않습니다.")
        revised = copy.deepcopy(c)
        target = revised["labs"][req["lab"]]
        for member in target["users"]:
            if hotops.name(spec, member) == old:
                member["container"] = new
        revised["labs"][req["lab"]] = replace_name(target, old, new)
        active = recovery.pause(spec)
        paused = True
        try:
            hotops.run("docker", "rename", before["Id"], new)
            renamed = True
            hotops.save(hotops.ETC / "policy.json", revised)
            hotops.save(path, replace_name(record, old, new))
            after = hotops.obj(new)
            if after["Id"] != before["Id"] or after["State"]["StartedAt"] != before["State"]["StartedAt"]:
                raise ValueError("환경 실행 상태가 변경되었습니다.")
        except Exception:
            if renamed:
                hotops.run("docker", "rename", before["Id"], old)
            hotops.save(hotops.ETC / "policy.json", c)
            hotops.save(path, record)
            raise
        return {"message": "컨테이너 이름과 관리 연결을 변경했습니다. 접속과 실행 작업은 유지됩니다."}
    finally:
        try:
            if paused:
                recovery.resume(spec, active)
        finally:
            hotops.JOB_LOCK.release()
