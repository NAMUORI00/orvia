"""Low-priority, cached storage accounting. File contents are never read."""

import json
import os
import pathlib
import stat
import subprocess
import sys
import threading
import time

import hotops

LOCK = threading.Lock()
ACTIVE = set()
ATTEMPTS = {}
TTL = 900


def scan(root, seconds=45, max_entries=10000000):
    start = time.monotonic()
    seen = set()
    nodes = {}
    count = 0
    partial = False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    root_fd = os.open(root, flags)
    device = os.fstat(root_fd).st_dev

    def walk(fd, path, depth):
        nonlocal count, partial
        total = os.fstat(fd).st_blocks * 512
        with os.scandir(fd) as iterator:
            for entry in iterator:
                if count >= max_entries or time.monotonic() - start > seconds:
                    partial = True
                    break
                count += 1
                if entry.name in {".admin", "lost+found"}:
                    continue
                if any(ord(c) < 32 for c in entry.name):
                    partial = True
                    continue
                child = path + "/" + entry.name if path else entry.name
                try:
                    meta = entry.stat(follow_symlinks=False)
                    if meta.st_dev != device or stat.S_ISLNK(meta.st_mode):
                        continue
                    key = (meta.st_dev, meta.st_ino)
                    if meta.st_nlink > 1 and stat.S_ISREG(meta.st_mode):
                        if key in seen:
                            continue
                        seen.add(key)
                    directory = stat.S_ISDIR(meta.st_mode)
                    size = meta.st_blocks * 512
                    if directory:
                        if depth >= 32:
                            partial = True
                        else:
                            child_fd = os.open(entry.name, flags, dir_fd=fd)
                            try:
                                opened = os.fstat(child_fd)
                                if (opened.st_dev, opened.st_ino) != key:
                                    partial = True
                                    continue
                                size = walk(child_fd, child, depth + 1)
                            finally:
                                os.close(child_fd)
                    total += size
                    # Store directory detail to four levels; scan all descendants.
                    if depth < 4:
                        if len(nodes) >= 20000 and depth == 0:
                            removable = next((p for p in nodes if "/" in p), None)
                            if removable is not None:
                                nodes.pop(removable)
                        if len(nodes) < 20000:
                            nodes[child] = dict(bytes=size, directory=directory)
                        else:
                            partial = True
                except OSError:
                    partial = True
        return total

    try:
        measured = walk(root_fd, "", 0)
        disk = os.fstatvfs(root_fd)
        return dict(
            schema_version=1,
            root=root,
            measured=measured,
            nodes=nodes,
            used=(disk.f_blocks - disk.f_bfree) * disk.f_frsize,
            capacity=disk.f_blocks * disk.f_frsize,
            partial=partial,
            entries=count,
            scanned_at=time.time(),
        )
    finally:
        os.close(root_fd)


def get(req):
    lab = req.get("lab")
    spec = hotops.cfg()["labs"].get(lab)
    if not spec:
        raise ValueError("등록된 연구실을 선택하세요.")
    root = str(pathlib.Path(spec["storage"]).resolve())
    if not os.path.ismount(root):
        raise ValueError("영구 저장공간 연결을 확인하세요.")
    folder = hotops.STATE / "usage"
    folder.mkdir(mode=0o700, exist_ok=True)
    cache = folder / (__import__("hashlib").sha256(root.encode()).hexdigest() + ".json")
    data = json.loads(cache.read_text()) if cache.exists() else None
    if (
        (not data or time.time() - data["scanned_at"] > TTL)
        and time.time() - ATTEMPTS.get(root, 0) > TTL
        and LOCK.acquire(False)
    ):
        ACTIVE.add(root)
        ATTEMPTS[root] = time.time()

        def worker():
            try:
                result = subprocess.check_output(
                    [
                        "nice",
                        "-n",
                        "19",
                        "ionice",
                        "-c",
                        "3",
                        sys.executable,
                        str(pathlib.Path(__file__).resolve()),
                        root,
                    ],
                    text=True,
                    timeout=60,
                    stderr=subprocess.PIPE,
                )
                hotops.save(cache, json.loads(result))
            except Exception:
                __import__("logging").exception("Storage accounting failed for %s", lab)
            finally:
                ACTIVE.discard(root)
                LOCK.release()

        threading.Thread(target=worker, daemon=True).start()
    if not data:
        return dict(
            state="scanning"
            if root in ACTIVE
            else "unavailable"
            if root in ATTEMPTS
            else "queued",
            root=root,
        )
    path = req.get("path", "")
    if path and (path not in data["nodes"] or not data["nodes"][path]["directory"]):
        raise ValueError("집계된 폴더를 선택하세요.")
    prefix = path + "/" if path else ""
    entries = [
        dict(path=p, name=p[len(prefix) :], **value)
        for p, value in data["nodes"].items()
        if p.startswith(prefix) and "/" not in p[len(prefix) :]
    ]
    entries.sort(key=lambda e: (-e["bytes"], e["name"]))
    accounts = [
        dict(
            name=u["name"],
            path=u["name"],
            bytes=data["nodes"].get(u["name"], {}).get("bytes", 0),
        )
        for u in spec["users"]
    ]
    accounts.sort(key=lambda e: -e["bytes"])
    return dict(
        state="ready",
        refreshing=root in ACTIVE,
        root=root,
        path=path,
        parent=path.rpartition("/")[0],
        accounts=accounts,
        entries=entries[:30],
        remaining=sum(e["bytes"] for e in entries[30:]),
        selected=data["nodes"][path]["bytes"] if path else data["measured"],
        **{
            k: data[k]
            for k in ["used", "capacity", "partial", "scanned_at", "measured"]
        },
    )


if __name__ == "__main__":
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    print(json.dumps(scan(sys.argv[1])))
