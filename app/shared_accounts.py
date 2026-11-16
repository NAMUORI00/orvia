"""Persistent, non-restarting account creation in a laboratory container.

Account databases are host-owned bind files. Updates preserve their inodes;
replacing a bind file would leave the running container on the old version.
"""
import crypt
import os
import pathlib
import re
import time

import account_profile
import hotops

DATABASES = ("passwd", "group", "shadow", "gshadow")


def password(req):
    """Change one existing password without restarting any environment."""
    value = req.get("password", "")
    if not isinstance(value, str) or not 8 <= len(value) <= 128 or any(ord(x) < 32 for x in value):
        raise ValueError("비밀번호는 8~128자로 입력하세요.")
    if value != req.get("password_confirm"):
        raise ValueError("새 비밀번호와 확인 값이 일치하지 않습니다.")
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    try:
        c, spec, user, obj = hotops.authorize(req)
        root = pathlib.Path(spec["storage"]).resolve()
        path = root / user.get("credential_dir", ".admin/" + ("shared" if spec.get("account_layout") == "shared" else user["name"])) / "shadow"
        if not os.path.ismount(root) or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("영구 계정 정보 연결을 확인하세요.")
        if not any(m["Destination"] == "/etc/shadow" and pathlib.Path(m["Source"]).resolve() == path for m in obj["Mounts"]):
            raise ValueError("선택한 계정의 비밀번호 저장 연결이 일치하지 않습니다.")
        original = path.read_text()
        rows = [line.split(":") for line in original.splitlines()]
        targets = [row for row in rows if row[0] == user["name"]]
        if len(targets) != 1:
            raise ValueError("선택한 계정 정보를 확인할 수 없습니다.")
        targets[0][1] = crypt.crypt(value, crypt.mksalt(crypt.METHOD_SHA512))
        targets[0][2] = str(int(time.time() // 86400))
        try:
            write_bound(path, "\n".join(":".join(row) for row in rows) + "\n")
        except Exception:
            write_bound(path, original)
            raise
        return {"message": "선택한 계정의 비밀번호를 변경했습니다. 다음 로그인부터 적용되며 기존 접속과 실행 작업은 유지됩니다."}
    finally:
        hotops.JOB_LOCK.release()


def write_bound(path, text):
    with path.open("r+", encoding="utf-8") as stream:
        stream.seek(0)
        stream.write(text)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def validate_shared(spec, obj):
    if spec.get("account_layout") != "shared":
        raise ValueError("연구실 공용 컨테이너 전환이 필요합니다. 기존 환경은 변경하지 않았습니다.")
    root = pathlib.Path(spec["storage"]).resolve()
    if not os.path.ismount(root):
        raise ValueError("연구실 영구 저장공간 연결을 확인하세요.")
    mounts = {m["Destination"]: m for m in obj["Mounts"]}
    expected = {"/home": root, **{"/etc/" + key: root / ".admin/shared" / key for key in DATABASES}}
    for target, source in expected.items():
        mount = mounts.get(target)
        if not mount or pathlib.Path(mount["Source"]).resolve() != source or (target == "/home" and not mount["RW"]):
            raise ValueError("공용 컨테이너의 영구 계정·저장 연결이 일치하지 않습니다.")
    if not obj["State"]["Running"]:
        raise ValueError("연구실 컨테이너를 먼저 시작하세요.")
    return root


def submit(req):
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    home = None
    old = {}
    registered = False
    try:
        c, spec, source_user, obj = hotops.authorize(req)
        root = validate_shared(spec, obj)
        name = req.get("new_user", "")
        password = req.get("password", "")
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,30}", name) or not 8 <= len(password) <= 128 or any(ord(x) < 32 for x in password):
            raise ValueError("계정 ID와 8자 이상의 비밀번호를 확인하세요.")
        if any(u["name"] == name for s in c["labs"].values() for u in s["users"]):
            raise ValueError("이미 등록된 계정입니다.")
        admin = root / ".admin/shared"
        old = {admin / key: (admin / key).read_text() for key in DATABASES}
        passwd = old[admin / "passwd"]
        group = old[admin / "group"]
        if any(line.split(":")[0] == name for line in passwd.splitlines()):
            raise ValueError("컨테이너에 이미 존재하는 계정입니다.")
        used = {int(row.split(":")[2]) for row in (passwd + group).splitlines() if row}
        used |= {u["uid"] for s in c["labs"].values() for u in s["users"]}
        uid = next(i for i in range(12000, 60001) if i not in used)
        home = root / name
        if home.exists() or home.is_symlink():
            home = None
            raise ValueError("사용자 저장 경로가 이미 존재합니다. 기존 자료를 먼저 확인하세요.")
        home.mkdir(mode=0o700)
        for child in (".tmp", ".cache", ".conda"):
            (home / child).mkdir(mode=0o700)
        (home / ".bashrc").write_text("[ ! -f /etc/profile.d/research.sh ] || . /etc/profile.d/research.sh\n")
        (home / ".bash_profile").write_text(". ~/.bashrc\n")
        for p in [home, *home.iterdir()]:
            os.chown(p, uid, uid)
        hashed = crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))
        changes = dict(old)
        changes[admin / "passwd"] += f"{name}:x:{uid}:{uid}::/home/{name}:/bin/bash\n"
        changes[admin / "shadow"] += f"{name}:{hashed}:{int(time.time()//86400)}:0:99999:7:::\n"
        for key, suffix in (("group", f"{name}:x:{uid}:\n"), ("gshadow", f"{name}:!::\n")):
            rows = old[admin / key].splitlines()
            for i, row in enumerate(rows):
                parts = row.split(":")
                if parts[0] == "orvia-research":
                    parts[3] = ",".join(filter(None, [parts[3], name]))
                    rows[i] = ":".join(parts)
                    break
            else:
                raise ValueError("연구실 SSH 허용 그룹이 없습니다.")
            changes[admin / key] = "\n".join(rows) + "\n" + suffix
        # Publish the password last. Existing account records are retained verbatim.
        for key in ("group", "gshadow", "passwd", "shadow"):
            write_bound(admin / key, changes[admin / key])
        container = hotops.name(spec, source_user)
        actual_uid = hotops.run("docker", "exec", container, "id", "-u", name)
        if actual_uid != str(uid):
            raise ValueError("컨테이너 계정 검증에 실패했습니다.")
        profile = account_profile.clean(req)
        profile["joined_on"] = profile.get("joined_on") or time.strftime("%Y-%m-%d")
        spec["users"].append(dict(name=name, container=container, port=source_user["port"], uid=uid, profile=profile, root_access=False))
        hotops.save(hotops.ETC / "policy.json", c)
        registered = True
        return {"message": "연구실 공용 컨테이너에 계정을 추가했습니다. 기존 접속과 실행 작업은 유지됩니다."}
    finally:
        try:
            if not registered:
                for path, content in old.items():
                    write_bound(path, content)
                if home is not None:
                    # Only the directory exclusively created by this transaction.
                    import shutil
                    shutil.rmtree(home)
        finally:
            hotops.JOB_LOCK.release()
