"""Minute-level infrastructure metrics; no command arguments or packet payloads."""

import collections, json, os, pathlib, sqlite3, subprocess, threading, time
import hotops
import history_store

INTERVAL = 60
RETENTION = 7 * 86400


def database():
    p = hotops.STATE / "telemetry.sqlite3"
    c = sqlite3.connect(p, timeout=3)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(
        "CREATE TABLE IF NOT EXISTS samples(ts INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS events(ts INTEGER, subject TEXT, kind TEXT, detail TEXT)"
    )
    p.chmod(0o600)
    return c


def network(pid):
    values = dict(rx=0, tx=0, rx_packets=0, tx_packets=0, drops=0, errors=0)
    try:
        for line in (
            pathlib.Path(f"/proc/{int(pid)}/net/dev").read_text().splitlines()[2:]
        ):
            name, raw = line.split(":", 1)
            if name.strip() == "lo":
                continue
            x = [int(v) for v in raw.split()]
            for k, v in zip(
                values, [x[0], x[8], x[1], x[9], x[3] + x[11], x[2] + x[10]]
            ):
                values[k] += v
        return values
    except (OSError, ValueError):
        return None


def sample(previous=None, processes=None):
    now = int(time.time())
    config = hotops.cfg()
    accounts = []
    processes = processes if processes is not None else {}
    names = [hotops.name(s, u) for s in config["labs"].values() for u in s["users"]]
    ids = hotops.run("docker", "ps", "-aq", timeout=10).split()
    objects = (
        json.loads(hotops.run("docker", "inspect", *ids, timeout=15)) if ids else []
    )
    lookup = {o["Name"].lstrip("/"): o for o in objects}
    running = [n for n in names if n in lookup and lookup[n]["State"]["Running"]]
    stats = {}
    if running:
        raw = hotops.run(
            "nice",
            "-n",
            "19",
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *running,
            timeout=20,
        )
        stats = {x["Name"]: x for x in (json.loads(line) for line in raw.splitlines())}
    prior = {a["container"]: a for a in (previous or {}).get("accounts", [])}
    for lab, s in config["labs"].items():
        for u in s["users"]:
            name = hotops.name(s, u)
            o = lookup.get(name)
            running = bool(o and o["State"]["Running"])
            a = dict(
                lab=lab,
                user=u["name"],
                container=name,
                running=running,
                identity=o["Id"] if o else "",
                started=o["State"]["StartedAt"] if o else "",
                cpu=None,
                memory=None,
                block_io=None,
                network=None,
                rates=None,
                processes=[],
            )
            if running:
                st = stats.get(name, {})
                try:
                    a["cpu"] = float(st.get("CPUPerc", "").rstrip("%"))
                except ValueError:
                    pass
                a["memory"] = st.get("MemUsage")
                a["block_io"] = st.get("BlockIO")
                a["network"] = network(o["State"]["Pid"])
                old = prior.get(name)
                dt = now - (previous or {}).get("ts", now)
                if (
                    old
                    and old["identity"] == a["identity"]
                    and old["started"] == a["started"]
                    and old.get("network")
                    and a["network"]
                    and dt > 0
                ):
                    a["rates"] = {
                        k: max(0, a["network"][k] - old["network"][k]) / dt
                        for k in a["network"]
                    }
                cached = processes.get(name, {})
                if (
                    cached.get("identity") != a["identity"]
                    or now - cached.get("time", 0) >= 300
                ):
                    try:
                        raw = hotops.run(
                            "nice",
                            "-n",
                            "19",
                            "docker",
                            "top",
                            name,
                            "-eo",
                            "pid,comm",
                            timeout=5,
                        )
                        counts = collections.Counter(
                            line.split(None, 1)[1]
                            for line in raw.splitlines()[1:]
                            if len(line.split(None, 1)) == 2
                        )
                        cached = dict(
                            identity=a["identity"],
                            time=now,
                            items=[
                                dict(name=k, count=v) for k, v in counts.most_common(10)
                            ],
                        )
                        processes[name] = cached
                    except subprocess.SubprocessError:
                        cached = {}
                a["processes"] = cached.get("items", [])
            accounts.append(a)
    gpus = []
    raw = hotops.run(
        "nvidia-smi",
        "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
        timeout=10,
    )
    for row in raw.splitlines():
        values = [v.strip() for v in row.split(",")]

        def num(v):
            try:
                return float(v)
            except ValueError:
                return None

        gpus.append(
            dict(
                zip(
                    ["index", "util", "used", "total", "temperature", "power"],
                    map(num, values),
                )
            )
        )
    mem = {
        l.split(":")[0]: int(l.split()[1]) * 1024
        for l in pathlib.Path("/proc/meminfo").read_text().splitlines()
        if l.startswith(("MemTotal:", "MemAvailable:"))
    }
    disks = []
    for lab, s in config["labs"].items():
        mounted = os.path.ismount(s["storage"])
        if mounted:
            st = os.statvfs(s["storage"])
            capacity = st.f_blocks * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
        else:
            capacity = used = None
        disks.append(
            dict(
                lab=lab,
                title=s["title"],
                mounted=mounted,
                capacity=capacity,
                used=used,
                gpu_indices=s.get("indices", [s.get("index")]),
            )
        )
    ticks = [
        int(x)
        for x in pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:9]
    ]
    cpu_total = sum(ticks)
    cpu_idle = ticks[3] + ticks[4]
    cpu_util = None
    if previous and cpu_total > previous.get("cpu_total", cpu_total):
        cpu_util = max(
            0,
            min(
                100,
                100
                * (
                    1
                    - (cpu_idle - previous["cpu_idle"])
                    / (cpu_total - previous["cpu_total"])
                ),
            ),
        )
    return dict(
        ts=now,
        cpu_total=cpu_total,
        cpu_idle=cpu_idle,
        cpu_util=cpu_util,
        accounts=accounts,
        gpus=gpus,
        disks=disks,
        load=os.getloadavg()[0],
        memory_used=mem["MemTotal"] - mem["MemAvailable"],
        memory_total=mem["MemTotal"],
        cpu_count=os.cpu_count(),
    )


def changes(old, new):
    events = []
    prior = {a["container"]: a for a in old.get("accounts", [])}
    for a in new["accounts"]:
        p = prior.get(a["container"])
        if p and p["running"] != a["running"]:
            events.append(
                (a["user"], "started" if a["running"] else "stopped", a["lab"])
            )
        elif p and p["started"] != a["started"] and a["running"]:
            events.append((a["user"], "restarted", a["lab"]))
    prior = {d["lab"]: d for d in old.get("disks", [])}
    for d in new["disks"]:
        p = prior.get(d["lab"])
        full = lambda x: bool(x.get("capacity") and x["used"] / x["capacity"] >= 0.9)
        if not d["mounted"] and (not p or p["mounted"]):
            events.append((d["title"], "mount_missing", d["lab"]))
        if full(d) and (not p or not full(p)):
            events.append((d["title"], "storage_high", d["lab"]))
    return events


def collect_forever():
    previous = None
    try:
        with database() as connection:
            latest = connection.execute(
                "SELECT payload FROM samples ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if latest:
                previous = json.loads(latest[0])
    except (sqlite3.Error, ValueError):
        pass
    processes = {}
    while True:
        start = time.monotonic()
        try:
            current = sample(previous, processes)
            with database() as c:
                c.execute(
                    "INSERT OR REPLACE INTO samples VALUES(?,?)",
                    (current["ts"], json.dumps(current)),
                )
                for subject, kind, detail in changes(previous or {}, current):
                    c.execute(
                        "INSERT INTO events VALUES(?,?,?,?)",
                        (current["ts"], subject, kind, detail),
                    )
                history_store.maintain(c, current["ts"], network_summary)
            previous = current
        except Exception:
            __import__("logging").exception("Infrastructure sample failed")
        time.sleep(max(5, INTERVAL - (time.monotonic() - start)))


def network_summary(samples):
    """Integrate raw counter deltas, never decimated graph points or reset counters."""
    result = {}
    previous = None
    for current in samples:
        prior = {(a["lab"], a["user"]): a for a in (previous or {}).get("accounts", [])}
        dt = current["ts"] - previous["ts"] if previous else 0
        for a in current["accounts"]:
            key = (a["lab"], a["user"])
            r = result.setdefault(
                key,
                dict(
                    lab=a["lab"],
                    user=a["user"],
                    rx=0,
                    tx=0,
                    rx_packets=0,
                    tx_packets=0,
                    errors=0,
                    drops=0,
                    seconds=0,
                    peak=0,
                    peak_ts=None,
                    incidents=[],
                ),
            )
            old = prior.get(key)
            if not (
                old
                and 0 < dt <= INTERVAL * 3
                and a.get("network")
                and old.get("network")
                and a.get("identity") == old.get("identity")
                and a.get("started") == old.get("started")
            ):
                continue
            delta = {
                k: a["network"][k] - old["network"][k]
                for k in ("rx", "tx", "rx_packets", "tx_packets", "errors", "drops")
            }
            if any(v < 0 for v in delta.values()):
                continue
            r["seconds"] += dt
            for k, v in delta.items():
                r[k] += v
            rate = (delta["rx"] + delta["tx"]) / dt
            if r["peak_ts"] is None or rate > r["peak"]:
                r["peak"], r["peak_ts"] = rate, current["ts"]
            if delta["errors"] or delta["drops"]:
                r["incidents"].append(
                    dict(ts=current["ts"], errors=delta["errors"], drops=delta["drops"])
                )
                r["incidents"] = r["incidents"][-20:]
        previous = current
    return sorted(result.values(), key=lambda r: r["rx"] + r["tx"], reverse=True)


def read(hours=2, start=None, end=None):
    now = int(time.time())
    if start is not None or end is not None:
        since, until = int(start), int(end)
        if (
            since < 0
            or until <= since
            or until - since > 31 * 86400
            or until > now + 86400
        ):
            raise ValueError("Select a date range of at most 31 days")
        historical = True
    else:
        hours = int(hours)
        if hours not in (2, 24, 168):
            raise ValueError("Invalid history window")
        since, until, historical = now - hours * 3600, now + 1, False
    with database() as c:
        result = history_store.query(c, since, until, network_summary)
    result["historical"] = historical
    return result


def retention(values=None):
    with database() as c:
        return history_store.settings(c, values)


def start():
    threading.Thread(target=collect_forever, daemon=True, name="orvia-metrics").start()
