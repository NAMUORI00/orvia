"""Add a separate account container to an existing shared laboratory mount."""

import crypt, json, os, pathlib, pwd, re, shutil, socket, subprocess, threading, time, uuid
import account_profile, hotops, lifecycle, maintenance, recovery


def validate(req, c, s):
    name = req.get("new_user", "")
    password = req.get("password", "")
    if (
        not re.fullmatch("[a-zA-Z][a-zA-Z0-9_-]{1,30}", name)
        or not 8 <= len(password) <= 128
        or any(ord(x) < 32 for x in password)
    ):
        raise ValueError("계정 ID와 8자 이상의 비밀번호를 확인하세요.")
    if any(u["name"] == name for lab in c["labs"].values() for u in lab["users"]):
        raise ValueError("이미 존재하는 계정입니다.")
    if not os.path.ismount(s["storage"]):
        raise ValueError("영구 저장공간 연결을 확인하세요.")
    if (pathlib.Path(s["storage"]) / name).exists() or (
        pathlib.Path(s["storage"]) / name
    ).is_symlink():
        raise ValueError("이미 존재하는 사용자 저장 경로입니다.")
    return name


def submit(req):
    c, s, u, o = hotops.authorize(req)
    name = validate(req, c, s)
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    job = dict(
        id=uuid.uuid4().hex[:12],
        lab=req["lab"],
        state="queued",
        kind="account",
        message="계정 생성 대기 중",
        time=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    (hotops.STATE / "jobs").mkdir(exist_ok=True)
    password_hash = crypt.crypt(req["password"], crypt.mksalt(crypt.METHOD_SHA512))
    profile = account_profile.clean(req)
    profile["joined_on"] = profile["joined_on"] or time.strftime("%Y-%m-%d")
    try:
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        threading.Thread(
            target=worker,
            args=(req["lab"], name, password_hash, profile, o, job),
            daemon=True,
        ).start()
    except Exception:
        hotops.JOB_LOCK.release()
        raise
    return {
        "message": "개별 사용자 환경 생성을 시작했습니다. 기존 계정은 계속 실행됩니다."
    }


def worker(lab, name, password_hash, profile, source, job):
    stage = hotops.STATE / "account-builds" / job["id"]
    container = None
    registered = False

    def progress(message):
        job.update(state="running", message=message)
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)

    try:
        c = hotops.cfg()
        s = c["labs"][lab]
        root = pathlib.Path(s["storage"])
        if not os.path.ismount(root):
            raise ValueError("Storage is not mounted")
        pending = [lifecycle.read_plan(p.stem) for p in lifecycle.PLANS.glob("*.json")]
        used = (
            {u["uid"] for spec in c["labs"].values() for u in spec["users"]}
            | {p.pw_uid for p in pwd.getpwall()}
            | {p["uid"] for p in pending}
        )
        uid = next(i for i in range(12000, 60001) if i not in used)
        bindings = source["HostConfig"].get("PortBindings", {}).get("2222/tcp")
        if not bindings:
            raise ValueError("SSH port configuration is missing")
        bind_ip = bindings[0].get("HostIp") or "0.0.0.0"
        ports = {u["port"] for spec in c["labs"].values() for u in spec["users"]} | {
            p["port"] for p in pending
        }
        port = None
        for candidate in range(2201, 65000):
            if candidate in ports:
                continue
            with socket.socket() as probe:
                try:
                    probe.bind((bind_ip, candidate))
                    port = candidate
                    break
                except OSError:
                    continue
        if not port:
            raise ValueError("No available SSH port")
        stage.mkdir(parents=True, mode=0o700)
        progress("개발환경 준비 중")
        (stage / "entrypoint.sh").write_text(
            (pathlib.Path(__file__).parent / "research-entrypoint.sh").read_text()
        )
        (stage / "Dockerfile").write_text(
            f"FROM {hotops.build_source(source['Image'])}\nRUN groupadd -g {uid} {name} && useradd -u {uid} -g {uid} -M -s /bin/bash {name}\nCOPY entrypoint.sh /usr/local/sbin/research-entrypoint\nRUN chmod 755 /usr/local/sbin/research-entrypoint\n"
        )
        image = hotops.run(
            "docker", "build", "-q", "--network=none", str(stage), timeout=300
        )
        shadow = hotops.run(
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint",
            "/bin/cat",
            image,
            "/etc/shadow",
        )
        rows = []
        for line in shadow.splitlines():
            fields = line.split(":")
            fields[1] = password_hash if fields[0] == name else "!"
            rows.append(":".join(fields))
        admin = root / ".admin" / name
        admin.mkdir(parents=True, mode=0o700)
        (root / ".admin").chmod(0o700)
        (admin / "shadow").write_text("\n".join(rows) + "\n")
        (admin / "shadow").chmod(0o600)
        keys = admin / "ssh"
        keys.mkdir(mode=0o700)
        hotops.run(
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(keys / "ssh_host_ed25519_key"),
        )
        home = root / name
        home.mkdir(mode=0o700)
        for d in [".tmp", ".cache", ".conda"]:
            (home / d).mkdir(mode=0o700)
        (home / ".bashrc").write_text(
            "[ ! -f /etc/profile.d/research.sh ] || . /etc/profile.d/research.sh\n"
        )
        (home / ".bash_profile").write_text(". ~/.bashrc\n")
        for p in [home, *home.iterdir()]:
            os.chown(p, uid, uid)
        net = lifecycle.network({"uid": uid, "id": lab})
        container = "lh-" + lab + "-" + name
        body = maintenance.create_payload(source)
        body.update(
            Image=image,
            Hostname=container,
            WorkingDir="/home/" + name,
            Entrypoint=["/usr/local/sbin/research-entrypoint"],
            Cmd=[],
        )
        body["Env"] = [
            e
            for e in body.get("Env", [])
            if e.split("=", 1)[0] not in ["RESEARCH_USER", "HOME", "USER", "LOGNAME"]
        ] + [
            "RESEARCH_USER=" + name,
            "HOME=/home/" + name,
            "USER=" + name,
            "LOGNAME=" + name,
        ]
        body["Labels"] = {"labharbor.lab": lab}
        h = body["HostConfig"]
        h["Binds"] = None
        h["Mounts"] = [
            dict(Type="bind", Source=str(home), Target="/home/" + name, ReadOnly=False),
            dict(
                Type="bind",
                Source=str(admin / "shadow"),
                Target="/etc/shadow",
                ReadOnly=True,
            ),
            dict(
                Type="bind", Source=str(keys), Target="/etc/research-ssh", ReadOnly=True
            ),
        ]
        h["ReadonlyRootfs"] = True
        h["CapDrop"] = ["ALL"]
        h["CapAdd"] = [
            "CHOWN",
            "DAC_OVERRIDE",
            "FOWNER",
            "SETGID",
            "SETUID",
            "SYS_CHROOT",
            "AUDIT_WRITE",
            "KILL",
        ]
        h["SecurityOpt"] = ["no-new-privileges:true"]
        h["PidsLimit"] = 4096
        h["Tmpfs"] = {
            "/tmp": "rw,nosuid,nodev,size=1073741824,mode=1777",
            "/run": "rw,nosuid,nodev,size=16777216,mode=755",
        }
        h["Devices"] = [
            dict(PathOnHost=d, PathInContainer=d, CgroupPermissions="rwm")
            for d in ["/dev/nvidia" + str(i) for i in s.get("indices", [s["index"]])]
            + ["/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools"]
        ]
        h["NetworkMode"] = net
        h["PortBindings"] = {"2222/tcp": [dict(HostIp=bind_ip, HostPort=str(port))]}
        h["RestartPolicy"] = {"Name": "no", "MaximumRetryCount": 0}
        body["NetworkingConfig"] = {"EndpointsConfig": {net: {}}}
        api = "/v" + maintenance.engine("GET", "/version")["ApiVersion"]
        progress("개별 사용자 환경 시작 중")
        new = maintenance.engine(
            "POST", api + "/containers/create?name=" + container, body
        )["Id"]
        maintenance.engine("POST", api + "/containers/" + new + "/start")
        for attempt in range(20):
            try:
                hotops.run(
                    "docker",
                    "exec",
                    new,
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
        created = hotops.obj(new)
        if not created["State"]["Running"]:
            raise ValueError("New environment did not start")
        visible = hotops.run(
            "docker",
            "exec",
            new,
            "nvidia-smi",
            "--query-gpu=uuid",
            "--format=csv,noheader",
        )
        if set(visible.splitlines()) != set(s.get("gpus", [s["gpu"]])):
            raise ValueError("GPU isolation verification failed")
        c = hotops.cfg()
        s = c["labs"][lab]
        s["users"].append(
            dict(name=name, container=container, uid=uid, port=port, profile=profile)
        )
        objects = [hotops.obj(hotops.name(s, u)) for u in s["users"]]
        files = recovery.install(lab, s, objects)
        try:
            hotops.save(hotops.ETC / "policy.json", c)
            registered = True
        except Exception:
            recovery.restore(files)
            raise
        job.update(state="complete", message="계정 생성 완료", account=name, port=port)
        shutil.rmtree(stage)
    except Exception:
        if container and not registered:
            subprocess.run(
                ["docker", "stop", "-t", "5", container],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        job.update(
            state="failed",
            message="계정 생성 중단. 기존 계정은 유지됩니다. 작업 기록을 확인하세요.",
        )
        __import__("logging").exception("Account provisioning failed for lab %s", lab)
    finally:
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        hotops.JOB_LOCK.release()
