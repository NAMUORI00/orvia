"""Root-owned management boundary. Policy precedes every mutation."""

import crypt, fcntl, json, os, pathlib, socketserver, subprocess, threading, time

ETC = pathlib.Path("/etc/h200-console")
STATE = pathlib.Path("/var/lib/h200-console")
SOCK = "/run/h200-console/control.sock"
LOCK = threading.Lock()
CACHE = {}


def run(*args, timeout=30):
    return subprocess.check_output(
        args, text=True, stderr=subprocess.PIPE, timeout=timeout
    ).strip()


def config():
    return json.loads((ETC / "policy.json").read_text())


def inspect(name):
    p = subprocess.run(
        ["docker", "inspect", name], capture_output=True, text=True, timeout=15
    )
    if p.returncode:
        return None
    return json.loads(p.stdout)[0]


def authorize(c, action, lab, user=None):
    if action in {"create", "recreate"}:
        raise PermissionError(
            "생성은 연구실 생성 화면에서, 재생성은 환경 관리 화면에서 실행하세요."
        )
    if action not in {"start", "stop", "password", "gpu_test", "grow"}:
        raise ValueError("지원하지 않는 작업입니다.")
    if lab not in c["labs"]:
        raise ValueError("등록되지 않은 연구실입니다.")
    if lab not in c["write_labs"]:
        raise PermissionError("관리 권한이 없는 연구실입니다.")
    spec = c["labs"][lab]
    if spec["gpu"] not in c["write_gpus"]:
        raise PermissionError("변경 허용 GPU가 아닙니다.")
    if user is not None and user not in [u["name"] for u in spec["users"]]:
        raise PermissionError("대상 계정이 연구실에 속하지 않습니다.")
    return spec


def audit(action, lab, user, result):
    STATE.mkdir(exist_ok=True)
    with (STATE / "audit.jsonl").open("a") as f:
        f.write(
            json.dumps(
                dict(
                    time=time.strftime("%Y-%m-%d %H:%M:%S"),
                    action=action,
                    lab=lab,
                    user=user,
                    result=result,
                ),
                ensure_ascii=False,
            )
            + "\n"
        )


def checked_container(c, s, u):
    name = u.get("container", s["prefix"] + u["name"])
    obj = inspect(name)
    if not obj:
        return None
    if s.get("sandbox"):
        assert obj["Config"]["Labels"].get("h200.console") == "sandbox"
        assert obj["Image"] == c["sandbox_image"]
    requests = obj["HostConfig"]["DeviceRequests"]
    assert len(requests) == 1 and requests[0]["DeviceIDs"] == s.get("gpus", [s["gpu"]])
    assert obj["HostConfig"]["Privileged"] is False
    expected_devices = {
        *("/dev/nvidia" + str(i) for i in s.get("indices", [s["index"]])),
        "/dev/nvidiactl",
        "/dev/nvidia-uvm",
        "/dev/nvidia-uvm-tools",
    }
    assert {d["PathOnHost"] for d in obj["HostConfig"]["Devices"]} == expected_devices
    assert obj["HostConfig"]["PidMode"] != "host"
    expected = str(pathlib.Path(s["storage"]) / u["name"])
    assert any(
        m["Source"] == expected and m["Destination"] == "/home/" + u["name"]
        for m in obj["Mounts"]
    )
    assert all(m["Source"].startswith(s["storage"] + "/") for m in obj["Mounts"])
    return obj


def snapshot():
    if time.monotonic() - CACHE.get("time", 0) < 5:
        return CACHE["data"]
    c = config()
    labs = []
    ids = run("docker", "ps", "-aq").split()
    objects = (
        {o["Name"].lstrip("/"): o for o in json.loads(run("docker", "inspect", *ids))}
        if ids
        else {}
    )
    for key, s in c["labs"].items():
        users = []
        for u in s["users"]:
            obj = objects.get(u.get("container", s["prefix"] + u["name"]))
            users.append(
                dict(
                    name=u["name"],
                    profile=__import__("account_profile").public(u),
                    port=u["port"],
                    status=obj["State"]["Status"] if obj else "未作成",
                    started=obj["State"]["StartedAt"] if obj else "",
                    container=u.get("container", s["prefix"] + u["name"]),
                )
            )
        st = os.statvfs(s["storage"])
        labs.append(
            dict(
                id=key,
                title=s["title"],
                storage_path=s["storage"],
                storage_file=s.get("disk", ""),
                gpu=s["index"],
                gpu_indices=s.get("indices", [s["index"]]),
                managed=s.get("managed", False),
                cpu=s.get("cpu"),
                ram=s.get("ram"),
                root_access=s.get("root_access", False),
                image=s.get("source_image", ""),
                users=users,
                sandbox=s.get("sandbox", False),
                writable=key in c["write_labs"] and s["gpu"] in c["write_gpus"],
                allocated_gb=round(pathlib.Path(s["disk"]).stat().st_size / 1e9, 1)
                if s.get("disk")
                else None,
                imported=s.get("imported", False),
                storage_gb=round(st.f_blocks * st.f_frsize / 1e9, 1),
                used_gb=round((st.f_blocks - st.f_bfree) * st.f_frsize / 1e9, 1),
            )
        )
    gpus = []
    for line in run(
        "nvidia-smi",
        "--query-gpu=index,uuid,utilization.gpu,memory.used,memory.total,temperature.gpu,name,driver_version",
        "--format=csv,noheader,nounits",
    ).splitlines():
        i, uuid, util, used, total, temp, name, driver = [
            x.strip() for x in line.split(",")
        ]
        gpus.append(
            dict(
                index=int(i),
                uuid=uuid,
                name=name,
                driver=driver,
                util=int(util),
                used=int(used),
                total=int(total),
                temp=int(temp),
            )
        )
    events = []
    if (STATE / "audit.jsonl").exists():
        events = [
            json.loads(x)
            for x in (STATE / "audit.jsonl").read_text().splitlines()[-15:]
        ][::-1]
    mem = {
        l.split(":")[0]: int(l.split()[1])
        for l in pathlib.Path("/proc/meminfo").read_text().splitlines()
        if l.startswith(("MemTotal:", "MemAvailable:"))
    }
    data = dict(
        labs=labs,
        gpus=gpus,
        events=events,
        load=os.getloadavg()[0],
        memory_used_gib=round((mem["MemTotal"] - mem["MemAvailable"]) / 1048576, 1),
        memory_total_gib=round(mem["MemTotal"] / 1048576),
        cpu_count=os.cpu_count(),
        cpu_model=next(
            (
                l.split(":", 1)[1].strip()
                for l in pathlib.Path("/proc/cpuinfo").read_text().splitlines()
                if l.startswith("model name")
            ),
            "N/A",
        )
        + " / "
        + str(os.cpu_count())
        + " threads",
        updated=time.strftime("%H:%M:%S"),
        mode="LabHarbor",
    )
    CACHE.update(time=time.monotonic(), data=data)
    return data


GPU_PROBE = """import ctypes,json
c=ctypes.CDLL('libcuda.so.1')
def ok(v):assert v==0,v
ok(c.cuInit(0));n=ctypes.c_int();ok(c.cuDeviceGetCount(ctypes.byref(n)));assert n.value>=1
d=ctypes.c_int();ok(c.cuDeviceGet(ctypes.byref(d),0));ctx=ctypes.c_void_p();ok(c.cuCtxCreate_v2(ctypes.byref(ctx),0,d))
p=ctypes.c_uint64();ok(c.cuMemAlloc_v2(ctypes.byref(p),ctypes.c_size_t(16)))
ok(c.cuMemsetD8_v2(p,65,16));b=ctypes.create_string_buffer(16);ok(c.cuMemcpyDtoH_v2(b,p,16));assert b.raw==b'A'*16
ok(c.cuMemFree_v2(p));ok(c.cuCtxDestroy_v2(ctx));print('CUDA PASS: allocation and transfer; visible GPUs:',n.value)"""


def operate(req):
    c = config()
    action = req.get("action")
    lab = req.get("lab")
    user = req.get("user") or None
    s = authorize(c, action, lab, user)
    if s.get("imported"):
        raise PermissionError("등록된 환경은 연구실 설정 화면에서 관리하세요.")
    assert req.get("confirm") == lab, "대상 연구실 확인이 필요합니다."
    members = [u for u in s["users"] if user is None or u["name"] == user]
    for u in members:
        checked_container(c, s, u)
    if action == "password":
        assert (
            user
            and isinstance(req.get("password"), str)
            and 10 <= len(req["password"]) <= 128
        ), "비밀번호는 10~128자입니다."
        p = pathlib.Path(s["storage"]) / ".admin" / user / "shadow"
        assert not p.is_symlink()
        h = crypt.crypt(req["password"], crypt.mksalt(crypt.METHOD_SHA512))
        with p.open("r+") as f:
            rows = [r.split(":") for r in f.read().splitlines()]
            assert sum(r[0] == user for r in rows) == 1
            for r in rows:
                if r[0] == user:
                    r[1] = h
            f.seek(0)
            f.write("\n".join(":".join(r) for r in rows) + "\n")
            f.truncate()
    elif action in {"start", "stop"} and not s.get("sandbox"):
        assert user is None, (
            "기존 복구 서비스와 연동하려면 연구실 전체 작업을 선택하세요."
        )
        run("systemctl", action, s["service"], timeout=120)
    elif action == "grow":
        assert user is None
        target = int(req["size_gb"]) * 1000000000
        disk = pathlib.Path(s["disk"])
        assert disk.stat().st_size < target <= c["max_storage_gb"] * 1000000000
        assert os.path.ismount(s["storage"])
        # Online ext4 growth: only append capacity; no shrink or unmount.
        source = run("findmnt", "-n", "-o", "SOURCE", "--target", s["storage"])
        assert (
            source.startswith("/dev/loop")
            and run("findmnt", "-n", "-o", "FSTYPE", "--target", s["storage"]) == "ext4"
        )
        assert json.loads(run("losetup", "--list", "--json", source))["loopdevices"][0][
            "back-file"
        ] == str(disk)
        free = os.statvfs(disk.parent)
        assert (
            free.f_bavail * free.f_frsize > target - disk.stat().st_size + 10000000000
        )
        run("fallocate", "-l", str(target), str(disk))
        run("losetup", "-c", source)
        run("resize2fs", source, timeout=120)
    else:
        for u in members:
            n = s["prefix"] + u["name"]
            obj = checked_container(c, s, u)
            if action == "start":
                run("docker", "start", n)
            elif action == "stop" and obj:
                run("docker", "stop", "-t", "15", n)
            elif action == "gpu_test":
                assert obj and obj["State"]["Running"]
                run(
                    "docker",
                    "exec",
                    "--user",
                    str(u["uid"]),
                    n,
                    "python",
                    "-c",
                    GPU_PROBE,
                )
    CACHE.clear()
    return {"message": "작업이 완료되었습니다."}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        req = {}
        try:
            self.connection.settimeout(10)
            raw = self.rfile.readline(8193)
            if len(raw) > 8192:
                raise ValueError("Request too large")
            req = json.loads(raw)
            with LOCK:
                if req.get("action") == "status":
                    result = snapshot()
                elif req.get("action") == "files":
                    import filebrowser

                    result = filebrowser.inspect(req)
                elif req.get("action") == "catalog":
                    import hotops

                    result = hotops.catalog()
                elif req.get("action") in {
                    "provision_plans",
                    "provision_submit",
                    "provision_prepare",
                }:
                    import lifecycle

                    result = (
                        lifecycle.plans()
                        if req["action"] == "provision_plans"
                        else lifecycle.prepare(req)
                        if req["action"] == "provision_prepare"
                        else lifecycle.submit(req)
                    )
                    CACHE.clear()
                elif req.get("action") in {
                    "metadata",
                    "account_metadata",
                    "account_create",
                    "environment_apply",
                    "gpu_reconfigure",
                    "maintenance_restart",
                    "maintenance_recreate",
                    "resources",
                    "backup",
                    "adduser",
                    "profile_save",
                    "register",
                }:
                    import hotops

                    result = hotops.dispatch(req)
                else:
                    result = operate(req)
            if req.get("action") not in {"status", "catalog"}:
                audit(req.get("action"), req.get("lab"), req.get("user"), "ok")
            response = {"ok": True, "data": result}
        except Exception as e:
            if req.get("action") not in {"status", "catalog"}:
                audit(
                    req.get("action"),
                    req.get("lab"),
                    req.get("user"),
                    "denied" if isinstance(e, PermissionError) else "failed",
                )
            response = {
                "ok": False,
                "error": str(e)
                if isinstance(e, (PermissionError, ValueError, AssertionError))
                else "관리 작업 실패. 서버 로그를 확인하세요.",
            }
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode())


if __name__ == "__main__":
    os.umask(0o077)
    pathlib.Path(SOCK).unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(SOCK, Handler) as server:
        import grp

        os.chown(SOCK, 0, grp.getgrnam("h200-console").gr_gid)
        os.chmod(SOCK, 0o660)
        server.serve_forever()
