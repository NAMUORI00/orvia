"""Bounded retention and incremental 15-minute archives for telemetry."""

import copy
import json
import time

STEP = 900
DEFAULT = {"raw_days": 7, "archive_days": 90}


def schema(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS history_settings(id INTEGER PRIMARY KEY, payload TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS rollups(ts INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
    )
    c.execute("CREATE INDEX IF NOT EXISTS events_time ON events(ts)")


def settings(c, values=None):
    schema(c)
    if values is not None:
        raw, archive = (
            int(values.get("raw_days", 7)),
            int(values.get("archive_days", 90)),
        )
        if raw not in (1, 3, 7) or archive not in (30, 60, 90, 180):
            raise ValueError("Invalid retention period")
        c.execute(
            "INSERT OR REPLACE INTO history_settings VALUES(1,?)",
            (json.dumps(dict(raw_days=raw, archive_days=archive)),),
        )
    row = c.execute("SELECT payload FROM history_settings WHERE id=1").fetchone()
    return json.loads(row[0]) if row else DEFAULT.copy()


def project(d):
    return dict(
        ts=d["ts"],
        load=d["load"],
        memory=d["memory_used"],
        cpu_util=d.get("cpu_util"),
        gpu=sum(g["util"] or 0 for g in d["gpus"]) / max(1, len(d["gpus"])),
        accounts=[
            dict(
                user=a["user"],
                lab=a["lab"],
                cpu=a["cpu"],
                rx=(a["rates"] or {}).get("rx"),
                tx=(a["rates"] or {}).get("tx"),
            )
            for a in d["accounts"]
        ],
    )


def average(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def aggregate(samples, predecessor, summarize):
    points = [project(d) for d in samples]
    point = copy.deepcopy(points[-1])
    peak = {}
    for key in ("load", "memory", "cpu_util", "gpu"):
        values = [p[key] for p in points if p[key] is not None]
        point[key] = average(values)
        peak[key] = max(values) if values else None
    accounts = {}
    for p in points:
        for a in p["accounts"]:
            accounts.setdefault((a["lab"], a["user"]), []).append(a)
    point["accounts"] = []
    for entries in accounts.values():
        a = entries[-1].copy()
        for key in ("cpu", "rx", "tx"):
            a[key] = average([e[key] for e in entries])
        a["cpu_peak"] = max(
            (e["cpu"] for e in entries if e["cpu"] is not None), default=None
        )
        point["accounts"].append(a)
    point["peak"] = peak
    latest = copy.deepcopy(samples[-1])
    for a in latest["accounts"]:
        a["processes"] = []
        a["network"] = None
    return dict(
        point=point,
        latest=latest,
        network=summarize(([predecessor] if predecessor else []) + samples),
    )


def maintain(c, now, summarize):
    """At most one hour of source samples per collection cycle; no full vacuum."""
    cfg = settings(c)
    closed = int(now) // STEP * STEP
    buckets = c.execute(
        "SELECT CAST(s.ts/? AS INTEGER)*? AS bucket FROM samples s LEFT JOIN rollups r ON r.ts=CAST(s.ts/? AS INTEGER)*? WHERE s.ts<? AND r.ts IS NULL GROUP BY bucket ORDER BY bucket LIMIT 4",
        (STEP, STEP, STEP, STEP, closed),
    ).fetchall()
    for (ts,) in buckets:
        samples = [
            json.loads(r[0])
            for r in c.execute(
                "SELECT payload FROM samples WHERE ts>=? AND ts<? ORDER BY ts",
                (ts, ts + STEP),
            )
        ]
        prior = c.execute(
            "SELECT payload FROM samples WHERE ts<? ORDER BY ts DESC LIMIT 1", (ts,)
        ).fetchone()
        c.execute(
            "INSERT OR REPLACE INTO rollups VALUES(?,?)",
            (
                ts,
                json.dumps(
                    aggregate(
                        samples, json.loads(prior[0]) if prior else None, summarize
                    )
                ),
            ),
        )
    # Never prune unarchived samples. Keep a predecessor for interval deltas.
    cutoff = (int(now) - cfg["raw_days"] * 86400) // STEP * STEP
    pending = c.execute(
        "SELECT 1 FROM samples s LEFT JOIN rollups r ON r.ts=CAST(s.ts/? AS INTEGER)*? WHERE s.ts<? AND r.ts IS NULL LIMIT 1",
        (STEP, STEP, cutoff),
    ).fetchone()
    if not pending:
        c.execute(
            "DELETE FROM samples WHERE ts<? AND ts<(SELECT MAX(ts) FROM samples WHERE ts<?)",
            (cutoff, cutoff),
        )
    expiry = (int(now) - cfg["archive_days"] * 86400) // STEP * STEP
    c.execute("DELETE FROM rollups WHERE ts<?", (expiry,))
    c.execute("DELETE FROM events WHERE ts<?", (expiry,))


def merge_network(groups):
    result = {}
    for group in groups:
        for a in group:
            key = (a["lab"], a["user"])
            if key not in result:
                result[key] = copy.deepcopy(a)
                continue
            r = result[key]
            for k in (
                "rx",
                "tx",
                "rx_packets",
                "tx_packets",
                "errors",
                "drops",
                "seconds",
            ):
                r[k] += a[k]
            if a["peak_ts"] is not None and (
                r["peak_ts"] is None or a["peak"] > r["peak"]
            ):
                r["peak"], r["peak_ts"] = a["peak"], a["peak_ts"]
            r["incidents"] = (r["incidents"] + a["incidents"])[-20:]
    return sorted(result.values(), key=lambda a: a["rx"] + a["tx"], reverse=True)


def query(c, since, until, summarize):
    cfg = settings(c)
    raw_start = since
    if until - since > 2 * 86400:
        last = c.execute(
            "SELECT MAX(ts) FROM rollups WHERE ts>=? AND ts+?<=?", (since, STEP, until)
        ).fetchone()[0]
        if last is not None:
            raw_start = last + STEP
    raw = [
        json.loads(r[0])
        for r in c.execute(
            "SELECT payload FROM samples WHERE ts>=? AND ts<? ORDER BY ts",
            (raw_start, until),
        )
    ]
    boundary = raw[0]["ts"] // STEP * STEP if raw else until
    archived = [
        json.loads(r[0])
        for r in c.execute(
            "SELECT payload FROM rollups WHERE ts>=? AND ts<? ORDER BY ts",
            (since, min(boundary, until)),
        )
    ]
    # A retained predecessor may be the sole raw row of an older bucket.
    if (
        raw
        and c.execute("SELECT 1 FROM rollups WHERE ts=?", (boundary,)).fetchone()
        and raw[0]["ts"] < int(time.time()) - cfg["raw_days"] * 86400
    ):
        extra = c.execute(
            "SELECT payload FROM rollups WHERE ts=?", (boundary,)
        ).fetchone()
        archived.append(json.loads(extra[0]))
        raw = [d for d in raw if d["ts"] >= boundary + STEP]
    prior = (
        c.execute(
            "SELECT payload FROM samples WHERE ts<? ORDER BY ts DESC LIMIT 1",
            (raw[0]["ts"],),
        ).fetchone()
        if raw
        else None
    )
    # Never count a predecessor interval twice across the archive/raw boundary.
    predecessor = json.loads(prior[0]) if prior else None
    if predecessor and predecessor["ts"] < since:
        predecessor = None
    networks = [a["network"] for a in archived]
    networks.append(summarize(([predecessor] if predecessor else []) + raw))
    points = [a["point"] for a in archived] + [project(d) for d in raw]
    bucket = max(60, (until - since) // 120)
    reduced = {}
    for point in points:
        reduced[int((point["ts"] - since) // bucket)] = point
    latest = raw[-1] if raw else archived[-1]["latest"] if archived else None
    events = [
        dict(ts=r[0], subject=r[1], kind=r[2], lab=r[3])
        for r in c.execute(
            "SELECT ts,subject,kind,detail FROM events WHERE ts>=? AND ts<? ORDER BY ts DESC LIMIT 100",
            (since, until),
        )
    ]
    return dict(
        latest=latest,
        history=list(reduced.values()),
        network_usage=merge_network(networks),
        events=events,
        settings=cfg,
        archive=bool(archived),
        from_ts=since,
        to_ts=until,
        interval=60,
        retention_days=cfg["archive_days"],
    )
