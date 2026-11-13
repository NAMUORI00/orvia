"""Prepare an official NVIDIA environment before interrupting any researcher."""

import json, pathlib, re, shutil, threading, time, uuid
import hotops, maintenance, reconfigure

PROVIDERS = {"cuda": "nvidia/cuda", "pytorch": "nvcr.io/nvidia/pytorch"}


def reference(provider, tag):
    if provider not in PROVIDERS or not re.fullmatch(
        "[A-Za-z0-9_.-]{1,100}", tag or ""
    ):
        raise ValueError("공식 이미지와 태그를 선택하세요.")
    if provider == "cuda" and "ubuntu" not in tag.lower():
        raise ValueError("SSH 연구환경 구성에는 Ubuntu 기반 이미지를 선택하세요.")
    return PROVIDERS[provider] + ":" + tag


def submit(req):
    c, s, u, o = hotops.authorize(req)
    source = reference(req.get("image_provider"), req.get("image_tag"))
    if (
        req.get("ack_downtime") != "yes"
        or req.get("ack_recreate") != "yes"
        or req.get("ack_environment") != "yes"
    ):
        raise ValueError("개발환경 교체와 작업 중단을 확인하세요.")
    objects = [hotops.obj(hotops.name(s, account)) for account in s["users"]]
    if reconfigure.fingerprint(objects) != req.get("expected_fingerprint"):
        raise ValueError("환경 상태가 변경되었습니다. 화면을 새로 열어 확인하세요.")
    for account, original in zip(s["users"], objects):
        maintenance.validate(s, account, original)
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError("다른 관리 작업이 진행 중입니다.")
    job = dict(
        id=uuid.uuid4().hex[:12],
        kind="environment",
        lab=req["lab"],
        state="queued",
        time=time.strftime("%Y-%m-%d %H:%M:%S"),
        message="공식 개발환경 준비 중",
    )
    (hotops.STATE / "jobs").mkdir(exist_ok=True)
    try:
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        threading.Thread(
            target=worker, args=(dict(req), source, objects, s, job), daemon=True
        ).start()
    except Exception:
        hotops.JOB_LOCK.release()
        raise
    return {
        "message": "공식 이미지 준비를 시작했습니다. 준비 검증 후 연구실 환경을 교체합니다."
    }


def worker(req, source, objects, spec, job):
    stage = hotops.STATE / "image-builds" / job["id"]
    applied = False

    def progress(message):
        job.update(state="running", message=message)
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)

    try:
        stage.mkdir(parents=True, mode=0o700)
        progress("공식 이미지 다운로드 중")
        hotops.run("docker", "pull", source, timeout=1800)
        base = hotops.build_source(source)
        images = {}
        for user, old in zip(spec["users"], objects):
            name = user["name"]
            uid = int(user["uid"])
            if not re.fullmatch("[a-zA-Z][a-zA-Z0-9_-]{1,30}", name):
                raise ValueError("Account name is not compatible")
            work = stage / name
            work.mkdir()
            (work / "entrypoint.sh").write_text(
                (pathlib.Path(__file__).parent / "research-entrypoint.sh").read_text()
            )
            (work / "research.sh").write_text(
                "export PATH=/opt/conda/bin:$PATH\nexport TMPDIR=$HOME/.tmp\nexport XDG_CACHE_HOME=$HOME/.cache\nexport CONDA_ENVS_PATH=$HOME/.conda/envs\n"
            )
            elevated = req.get("root_access") == "yes"
            sudo = (
                f"RUN printf '%s\\n' '{name} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/research && chmod 440 /etc/sudoers.d/research\n"
                if elevated
                else ""
            )
            (work / "Dockerfile").write_text(
                f"FROM {base}\nUSER root\nRUN command -v apt-get && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server sudo python3 python3-venv python3-pip git ca-certificates && rm -rf /var/lib/apt/lists/*\nRUN groupadd -g {uid} {name} && useradd -u {uid} -g {uid} -M -s /bin/bash {name}\nCOPY entrypoint.sh /usr/local/sbin/research-entrypoint\nCOPY research.sh /etc/profile.d/research.sh\nRUN chmod 755 /usr/local/sbin/research-entrypoint\nENV RESEARCH_USER={name}\n"
                + sudo
            )
            progress("사용자 개발환경 구성 중")
            image = hotops.run(
                "docker",
                "build",
                "-q",
                "--memory=4g",
                "--cpu-quota=200000",
                str(work),
                timeout=1800,
            )
            hotops.run(
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--entrypoint",
                "/bin/sh",
                image,
                "-c",
                "id "
                + name
                + " && test -x /usr/sbin/sshd && test -x /usr/local/sbin/research-entrypoint",
                timeout=30,
            )
            images[old["Name"].lstrip("/")] = image
        progress("개발환경 교체 중")
        request = dict(
            req,
            gpu_selection=",".join(
                str(i) for i in spec.get("indices", [spec["index"]])
            ),
        )
        reconfigure.apply(
            request,
            images=images,
            lock_owned=True,
            source_image=source,
            root_access=req.get("root_access") == "yes",
        )
        applied = True
        # Persist only observed/configured environment facts, never carry old version text forward.
        try:
            info = hotops.run(
                "docker",
                "exec",
                objects[0]["Name"].lstrip("/"),
                "/bin/sh",
                "-c",
                "python3 --version; if command -v conda >/dev/null 2>&1; then conda --version; fi",
                timeout=20,
            )
            path = hotops.ETC / "web.json"
            config = json.loads(path.read_text())
            profile = config.setdefault("document_labs", {}).setdefault(req["lab"], {})
            profile.update(
                schema_version=1,
                environment_ko=source + "\n" + info,
                environment_en=source + "\n" + info,
                permissions_ko="컨테이너 내부 sudo 사용 가능. 호스트 Docker 관리 권한 없음."
                if req.get("root_access") == "yes"
                else "일반 사용자 환경. 호스트 Docker 관리 권한 없음.",
                permissions_en="Container sudo access. No host Docker administration."
                if req.get("root_access") == "yes"
                else "Standard user environment. No host Docker administration.",
            )
            meta = path.stat()
            temp = path.with_suffix(".next")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2))
            __import__("os").chmod(temp, meta.st_mode & 0o777)
            __import__("os").chown(temp, meta.st_uid, meta.st_gid)
            temp.replace(path)
            job.update(state="complete", message="개발환경 교체 완료")
        except Exception:
            job.update(
                state="complete",
                message="개발환경 교체 완료 · 안내서 환경 정보 확인 필요",
            )
        shutil.rmtree(stage)
    except Exception:
        job.update(
            state="failed",
            message="개발환경 교체 중단. 작업 기록과 복구 상태를 확인하세요.",
        )
        __import__("logging").exception(
            "Environment update failed for lab %s", req["lab"]
        )
    finally:
        hotops.save(hotops.STATE / "jobs" / (job["id"] + ".json"), job)
        hotops.JOB_LOCK.release()
