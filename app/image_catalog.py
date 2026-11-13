"""Bounded official-provider tag catalog; failures retain the previous cached list."""

import json, time, urllib.request, threading, re

CACHE = {}
LOCK = threading.Lock()
SOURCES = {
    "cuda": (
        "https://hub.docker.com/v2/repositories/nvidia/cuda/tags?page_size=50",
        "nvidia/cuda",
    ),
    "pytorch": (
        "https://nvcr.io/v2/nvidia/pytorch/tags/list",
        "nvcr.io/nvidia/pytorch",
    ),
}


def catalog(provider):
    if provider not in SOURCES:
        raise ValueError("Unknown provider")
    with LOCK:
        old = CACHE.get(provider)
        if old and time.time() - old["time"] < 900:
            return old
        url, repo = SOURCES[provider]
        try:
            headers = {"User-Agent": "Orvia/0.6"}
            if provider == "pytorch":
                with urllib.request.urlopen(
                    "https://nvcr.io/proxy_auth?scope=repository:nvidia/pytorch:pull&service=nvcr.io",
                    timeout=8,
                ) as auth:
                    token = json.load(auth)["token"]
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as res:
                d = json.load(res)
            items = d.get("results", d.get("tags", []))
            if provider == "pytorch":
                items = sorted(
                    [
                        x
                        for x in items
                        if isinstance(x, str)
                        and re.match(r"^\d{2}\.\d{2}(?:[-.]|$)", x)
                    ],
                    reverse=True,
                )
            tags = []
            for item in items:
                tag = (
                    item
                    if isinstance(item, str)
                    else item.get("name") or item.get("tag") or item.get("version")
                )
                if tag:
                    tags.append(
                        dict(
                            tag=tag,
                            image=repo + ":" + tag,
                            updated=item.get("last_updated", "")
                            if isinstance(item, dict)
                            else "",
                        )
                    )
            if not tags:
                raise ValueError("Empty catalog")
            result = dict(
                provider=provider,
                repository=repo,
                tags=tags[:100],
                time=time.time(),
                stale=False,
            )
            CACHE[provider] = result
            return result
        except Exception:
            if old:
                return {**old, "stale": True}
            return dict(
                provider=provider,
                repository=repo,
                tags=[],
                stale=True,
                error="공식 이미지 목록을 가져오지 못했습니다. 잠시 후 다시 시도하세요.",
            )
