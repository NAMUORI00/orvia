"""Bounded, read-only text browsing within configured laboratory mounts."""

import os
import pathlib
import stat
import hotops

LIMIT = 65536


def parts(value):
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError("허용되지 않은 파일 경로입니다.")
    result = value.split("/") if value else []
    if any(
        not p or p.startswith(".") or p == "lost+found" or any(ord(c) < 32 for c in p)
        for p in result
    ):
        raise ValueError("숨김 파일과 관리용 경로는 열 수 없습니다.")
    return result


def inspect(req):
    spec = hotops.cfg()["labs"].get(req.get("lab"))
    if not spec:
        raise PermissionError("등록된 연구실을 선택하세요.")
    path = str(spec["storage"])
    if not os.path.ismount(path):
        raise ValueError("영구 저장공간 연결을 확인하세요.")
    components = parts(req.get("path", ""))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags | os.O_DIRECTORY)
    try:
        device = os.fstat(fd).st_dev
        for i, component in enumerate(components):
            new = os.open(
                component,
                flags | (os.O_DIRECTORY if i < len(components) - 1 else 0),
                dir_fd=fd,
            )
            os.close(fd)
            fd = new
            if os.fstat(fd).st_dev != device:
                raise ValueError("다른 저장장치로 연결된 경로는 열 수 없습니다.")
        info = os.fstat(fd)
        result = dict(
            path="/".join(components),
            root=path,
            parent="/".join(components[:-1]),
            size=info.st_size,
        )
        if stat.S_ISDIR(info.st_mode):
            entries = []
            scanned = 0
            truncated = False
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    scanned += 1
                    if scanned > 1000 or len(entries) >= 150:
                        truncated = True
                        break
                    try:
                        parts(entry.name)
                        meta = entry.stat(follow_symlinks=False)
                        directory = stat.S_ISDIR(meta.st_mode)
                        if (
                            meta.st_dev != device
                            or not (directory or stat.S_ISREG(meta.st_mode))
                            or (not directory and meta.st_nlink > 1)
                        ):
                            continue
                        entries.append(
                            dict(
                                name=entry.name,
                                directory=directory,
                                size=meta.st_size,
                                path="/".join(components + [entry.name]),
                            )
                        )
                    except (ValueError, OSError):
                        continue
            result.update(
                kind="directory",
                entries=sorted(
                    entries, key=lambda e: (not e["directory"], e["name"].casefold())
                ),
                truncated=truncated,
            )
        else:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("일반 텍스트 파일만 열 수 있습니다.")
            if info.st_size > LIMIT:
                raise ValueError("미리보기는 64 KiB 이하 텍스트 파일만 지원합니다.")
            raw = os.read(fd, LIMIT + 1)
            if len(raw) > LIMIT or b"\x00" in raw:
                raise ValueError("일반 텍스트 파일만 열 수 있습니다.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise ValueError("UTF-8 텍스트 파일만 열 수 있습니다.") from None
            if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                raise ValueError("일반 텍스트 파일만 열 수 있습니다.")
            result.update(kind="file", text=text)
        return result
    except OSError:
        raise ValueError("파일이 없거나 접근할 수 없는 경로입니다.") from None
    finally:
        os.close(fd)
