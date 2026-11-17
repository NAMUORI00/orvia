(async () => {
  const messages = await fetch("/api/translations").then((r) => r.json()),
    t = (s) => messages[s] || s,
    V = window.OrviaViz;
  const el = (id) => document.getElementById(id),
    node = (tag, value, cls) => {
      const n = document.createElement(tag);
      n.textContent = value || "";
      if (cls) n.className = cls;
      return n;
    };
  const size = (n) =>
    n == null
      ? "N/A"
      : n >= 1e12
        ? (n / 1e12).toFixed(2) + " TB"
        : n >= 1e9
          ? (n / 1e9).toFixed(1) + " GB"
          : n >= 1e6
            ? (n / 1e6).toFixed(1) + " MB"
            : (n / 1024).toFixed(1) + " KiB";
  const mibToGb = (mib) => (mib == null ? "N/A" : (mib / 1024).toFixed(1) + " GB");
  const colors = ["#218878", "#5b88bd", "#9872b4", "#cb984d"];
  let selectedLab = null;
  let data,
    timer,
    selected = null,
    dialogKind = null;

  const totals = (h, key) => {
    const a = h.accounts.map((a) => a[key]).filter((v) => v != null);
    return a.length ? a.reduce((a, b) => a + b, 0) : null;
  };
  function series(container, label, points, format, color, max) {
    const graph = V.svg("svg", { class: "insight-chart" });
    container.append(graph);
    V.chart(graph, points, { label, format, color, max });
    return graph;
  }
  function statusForPct(p) {
    if (p == null) return { badge: "sig-idle", arc: "is-teal", label: "수집 대기" };
    if (p >= 85) return { badge: "sig-crit", arc: "is-crit", label: "혼잡" };
    if (p >= 65) return { badge: "sig-warn", arc: "is-amber", label: "주의" };
    if (p >= 25) return { badge: "sig-info", arc: "is-sky", label: "활발" };
    if (p >= 5) return { badge: "sig-safe", arc: "is-teal", label: "쾌적" };
    return { badge: "sig-safe", arc: "is-teal", label: "여유" };
  }
  function buildGaugeSvg(pct, centerMain, centerSub, { innerPct = null, arcCls = null } = {}) {
    const clamped = pct == null ? 0 : Math.max(0, Math.min(100, pct));
    const vis = clamped === 0 ? 0 : Math.max(2.2, clamped);
    const st = statusForPct(pct);
    const arcD = "M 44.7 125.3 A 64 64 0 1 1 135.3 125.3";
    const innerD = "M 54.6 115.4 A 50 50 0 1 1 125.4 115.4";
    const svg = V.svg("svg", {
      class: "cockpit-gauge-svg",
      viewBox: "0 0 180 148",
      role: "img",
      "aria-label": centerSub + " " + centerMain,
    });
    for (const [x, y, txt] of [
      [34, 139, "0"],
      [90, 11, "50"],
      [146, 139, "100"],
    ]) {
      const tick = V.svg("text", { class: "gauge-scale-tick", x, y, "text-anchor": "middle" });
      tick.textContent = txt;
      svg.append(tick);
    }
    svg.append(V.svg("path", { class: "gauge-track", d: arcD, pathLength: 100 }));
    if (vis > 0) {
      svg.append(
        V.svg("path", {
          class: "gauge-arc " + (arcCls || st.arc),
          d: arcD,
          pathLength: 100,
          "stroke-dasharray": vis.toFixed(1) + " 100",
        }),
      );
    }
    if (innerPct != null) {
      const iv = innerPct === 0 ? 0 : Math.max(2.2, Math.min(100, innerPct));
      svg.append(V.svg("path", { class: "gauge-track-inner", d: innerD, pathLength: 100 }));
      if (iv > 0) {
        svg.append(
          V.svg("path", {
            class: "gauge-arc-inner" + (innerPct >= 80 ? " is-warn" : ""),
            d: innerD,
            pathLength: 100,
            "stroke-dasharray": iv.toFixed(1) + " 100",
          }),
        );
      }
    }
    const valText = V.svg("text", { class: "gauge-center-val", x: 90, y: 79, "text-anchor": "middle" });
    valText.textContent = centerMain;
    const subText = V.svg("text", { class: "gauge-center-sub", x: 90, y: 96, "text-anchor": "middle" });
    subText.textContent = centerSub;
    svg.append(valText, subText);
    return svg;
  }
  function buildMiniRing(pct, label, subtext, colorCls) {
    const cell = node("div", "", "mini-ring-cell");
    const c = pct == null ? 0 : Math.max(0, Math.min(100, pct));
    const vis = c === 0 ? 0 : Math.max(3, c);
    const arcD = "M 18.8 55.2 A 26 26 0 1 1 55.2 55.2";
    const svg = V.svg("svg", {
      class: "mini-ring-svg",
      viewBox: "0 0 74 64",
      role: "img",
      "aria-label": label,
    });
    svg.append(V.svg("path", { class: "mini-gauge-track", d: arcD, pathLength: 100 }));
    if (vis > 0) {
      svg.append(
        V.svg("path", {
          class: "mini-gauge-arc " + colorCls,
          d: arcD,
          pathLength: 100,
          "stroke-dasharray": vis.toFixed(1) + " 100",
        }),
      );
    }
    const txt = V.svg("text", { class: "mini-gauge-val", x: 37, y: 40, "text-anchor": "middle" });
    txt.textContent = pct == null ? "N/A" : c < 10 && c > 0 ? c.toFixed(1) + "%" : Math.round(c) + "%";
    svg.append(txt);
    cell.append(svg, node("strong", t(label)), node("small", subtext));
    return cell;
  }
  function buildSvgBar(pct, fillCls = "meter-svg-fill-teal") {
    const w = pct == null ? 0 : Math.max(0, Math.min(100, pct));
    const svg = V.svg("svg", {
      class: "meter-svg",
      viewBox: "0 0 100 9",
      preserveAspectRatio: "none",
      "aria-hidden": "true",
    });
    svg.append(
      V.svg("rect", { class: "meter-svg-bg", x: 0, y: 0, width: 100, height: 9, rx: 4.5 }),
      V.svg("rect", { class: fillCls, x: 0, y: 0, width: w.toFixed(1), height: 9, rx: 4.5 }),
    );
    return svg;
  }
  function issues() {
    const d = data.latest;
    return [
      ...d.accounts
        .filter((a) => !a.running)
        .map((a) => a.user + " · " + t("환경 정지")),
      ...d.disks
        .filter((d) => !d.mounted || (d.capacity && d.used / d.capacity >= 0.9))
        .map(
          (d) =>
            d.title +
            " · " +
            t(d.mounted ? "저장공간 90% 이상" : "저장공간 연결 끊김"),
        ),
      ...d.gpus
        .filter((g) => g.temperature >= 85)
        .map((g) => "GPU " + g.index + " · " + t("온도 확인")),
    ];
  }
  function memoryBytes(value) {
    const m = /^\s*([\d.]+)\s*(B|KiB|MiB|GiB|TiB|kB|MB|GB|TB)/.exec(
      value || "",
    );
    return m
      ? Number(m[1]) *
          {
            B: 1,
            KiB: 1024,
            MiB: 1024 ** 2,
            GiB: 1024 ** 3,
            TiB: 1024 ** 4,
            kB: 1000,
            MB: 1e6,
            GB: 1e9,
            TB: 1e12,
          }[m[2]]
      : null;
  }
  function sumKnown(values) {
    return values.length && values.every((v) => v != null && Number.isFinite(v))
      ? values.reduce((a, b) => a + b, 0)
      : null;
  }
  function meter(parent, label, value, max, format, extra = "") {
    const box = node("div", "", "resource-meter");
    box.append(node("span", t(label)));
    const pct = value == null || !(max > 0) ? 0 : (value / max) * 100;
    const svg = buildSvgBar(pct, "meter-svg-fill-teal");
    svg.setAttribute("tabindex", "0");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", t(label));
    const text =
      t(label) +
      " · " +
      (value == null ? "N/A" : format(value)) +
      (max > 0 ? " / " + format(max) : "") +
      (extra ? "\n" + extra : "");
    V.hint(svg, text);
    svg.onclick = () => V.show(text, svg);
    box.append(svg);
    if (value == null || !(max > 0)) box.append(node("small", "N/A"));
    parent.append(box);
  }
  function renderHeadroom() {
    const d = data.latest;
    const strip = el("monitor-headroom");
    strip.replaceChildren();
    const hs = data.host_summary || {};
    const ownedMap = hs.gpu_owners || {};
    const assignedIdxs = new Set([
      ...Object.keys(ownedMap).map(Number),
      ...d.disks.flatMap((s) => s.gpu_indices || []),
    ]);
    const freeGpus = d.gpus.filter((g) => !assignedIdxs.has(g.index));
    const freeVramGb = freeGpus.reduce((n, g) => n + (g.total || 0) / 1024, 0);
    const totalCpu = d.cpu_count || 0;
    const cpuUtil = d.cpu_util ?? 0;
    const freeCpu = Math.max(0, totalCpu * (1 - cpuUtil / 100));
    const memTotal = (d.memory_total || 0) / 1073741824;
    const memUsed = (d.memory_used || 0) / 1073741824;
    const memFree = Math.max(0, memTotal - memUsed);

    const addCell = (label, mainStr, subStr) => {
      const c = node("div", "", "headroom-cell");
      const s = node("strong", mainStr + " ");
      if (subStr) s.append(node("small", subStr));
      c.append(node("span", t(label)), s);
      strip.append(c);
    };

    addCell(
      "서버 여유 GPU",
      freeGpus.length + " / " + d.gpus.length,
      "(" + freeVramGb.toFixed(0) + " GB " + t("미배정 할당 가능") + ")",
    );
    addCell(
      "서버 여유 CPU",
      freeCpu.toFixed(1) + " / " + totalCpu + " " + t("코어"),
      "(" + (100 - cpuUtil).toFixed(1) + "%)",
    );
    addCell(
      "서버 여유 RAM",
      memFree.toFixed(0) + " / " + memTotal.toFixed(0) + " GiB",
      memTotal > 0 ? "(" + ((memFree / memTotal) * 100).toFixed(1) + "%)" : "",
    );
    if (hs.pool_total_bytes) {
      addCell(
        "서버 여유 디스크",
        size(hs.pool_free_bytes) + " / " + size(hs.pool_total_bytes),
        t("증설 가능"),
      );
    } else {
      const labCap = sumKnown(d.disks.map((s) => s.capacity));
      const labUsed = sumKnown(d.disks.map((s) => s.used));
      addCell(
        "연구실 디스크 여유",
        labCap != null && labUsed != null ? size(Math.max(0, labCap - labUsed)) : "N/A",
        labCap != null ? "/ " + size(labCap) : "",
      );
    }
  }
  function renderGpuRack() {
    const d = data.latest;
    const rack = el("monitor-gpu-rack");
    rack.replaceChildren();
    const hs = data.host_summary || {};
    const gpuOwners = hs.gpu_owners || {};
    const gpuLabIds = hs.gpu_lab_ids || {};

    d.gpus.forEach((g) => {
      let ownerLabId = gpuLabIds[String(g.index)] || null;
      let ownerTitle = gpuOwners[String(g.index)] || null;
      if (!ownerLabId) {
        const diskOwner = d.disks.find((s) => (s.gpu_indices || []).includes(g.index));
        if (diskOwner) {
          ownerLabId = diskOwner.lab;
          ownerTitle = diskOwner.title;
        }
      }
      const tile = node(
        "article",
        "",
        "gpu-rack-tile" +
          (!ownerLabId ? " unassigned" : "") +
          (ownerLabId && ownerLabId === selectedLab ? " active" : ""),
      );
      tile.setAttribute("tabindex", "0");
      tile.setAttribute("role", "button");
      tile.onclick = () => {
        if (ownerLabId) {
          selectedLab = ownerLabId;
          render();
          el("lab-users-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } else {
          open("hardware");
        }
      };
      tile.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          tile.click();
        }
      };

      const head = node("div", "", "gpu-tile-head");
      const tempVal = g.temperature;
      const tempCls = tempVal >= 80 ? "sig-crit" : tempVal >= 62 ? "sig-warn" : "sig-safe";
      head.append(
        node("strong", "GPU " + g.index),
        node("span", (tempVal ?? "N/A") + " °C", "sig-badge " + tempCls),
      );
      const ownerEl = node(
        "div",
        ownerTitle || t("미배정 여유"),
        "gpu-tile-owner" + (!ownerLabId ? " is-free" : ""),
      );
      tile.append(head, ownerEl);

      if (ownerLabId) {
        const smPct = g.util ?? 0;
        const vramPct = g.total ? ((g.used || 0) / g.total) * 100 : 0;
        const smRow = node("div", "", "gpu-tile-row");
        smRow.append(node("span", "SM"), node("strong", (g.util ?? "N/A") + "%"));
        const vRow = node("div", "", "gpu-tile-row");
        vRow.append(
          node("span", "VRAM"),
          node("strong", mibToGb(g.used) + " / " + mibToGb(g.total)),
        );
        tile.append(
          smRow,
          buildSvgBar(smPct, smPct >= 75 ? "meter-svg-fill-amber" : "meter-svg-fill-teal"),
          vRow,
          buildSvgBar(vramPct, vramPct >= 80 ? "meter-svg-fill-amber" : "meter-svg-fill-sky"),
        );
      } else {
        tile.append(
          node(
            "div",
            t("신규 할당 가능") + " · " + mibToGb(g.total),
            "gpu-free-banner",
          ),
        );
      }
      tile.append(node("div", (g.power ?? "N/A") + " W", "gpu-tile-power"));
      rack.append(tile);
    });
  }
  function renderLabs() {
    const d = data.latest,
      grid = el("monitor-labs");
    grid.replaceChildren();
    if (!d.disks.some((s) => s.lab === selectedLab)) selectedLab = d.disks[0]?.lab || null;
    const network = data.network_usage || [];

    d.disks.forEach((s) => {
      const card = node("article", "", "cockpit-card is-interactive");
      card.classList.toggle("selected", s.lab === selectedLab);
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute("aria-pressed", String(s.lab === selectedLab));
      card.onclick = () => {
        selectedLab = s.lab;
        render();
      };
      card.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          card.click();
        }
      };

      const accounts = d.accounts.filter((a) => a.lab === s.lab);
      const runningCnt = accounts.filter((a) => a.running).length;
      const gpus = d.gpus.filter((g) => (s.gpu_indices || []).includes(g.index));

      const head = node("div", "", "cockpit-card-head");
      const titleWrap = document.createElement("div");
      titleWrap.append(
        node("strong", s.title),
        node(
          "div",
          "GPU " +
            ((s.gpu_indices || []).join(", ") || "—") +
            " · " +
            runningCnt +
            " / " +
            accounts.length +
            " " +
            t("실행 중"),
          "muted",
        ),
      );
      head.append(titleWrap, node("span", "›"));
      card.append(head);

      const gpuPct =
        gpus.length && gpus.every((g) => g.util != null)
          ? sumKnown(gpus.map((g) => g.util)) / gpus.length
          : null;
      const cpuSum = sumKnown(
        accounts.map((a) => (a.running ? (a.cpu == null ? null : a.cpu / 100) : 0)),
      );
      const cpuPct = cpuSum != null && d.cpu_count > 0 ? (cpuSum / d.cpu_count) * 100 : null;
      const ramSum = sumKnown(
        accounts.map((a) => (a.running ? memoryBytes(a.memory) : 0)),
      );
      const ramPct = ramSum != null && d.memory_total > 0 ? (ramSum / d.memory_total) * 100 : null;
      const diskPct = s.used != null && s.capacity > 0 ? (s.used / s.capacity) * 100 : null;

      const rings = node("div", "", "lab-mini-rings-4");
      rings.append(
        buildMiniRing(
          gpuPct,
          "GPU",
          gpus.length + "×",
          gpuPct != null && gpuPct >= 75 ? "is-amber" : "is-teal",
        ),
        buildMiniRing(
          cpuPct,
          "CPU",
          cpuSum == null ? "N/A" : cpuSum.toFixed(1) + "c",
          "is-sky",
        ),
        buildMiniRing(
          ramPct,
          "메모리",
          ramSum == null ? "N/A" : (ramSum / 1073741824).toFixed(0) + "G",
          "is-purple",
        ),
        buildMiniRing(
          diskPct,
          "디스크",
          s.used == null ? "N/A" : size(s.used),
          diskPct != null && diskPct >= 75 ? "is-amber" : "is-green",
        ),
      );
      card.append(rings);

      const net = network.filter((a) => a.lab === s.lab);
      const netBytes = net.some((a) => a.seconds)
        ? net.reduce((n, a) => n + a.rx + a.tx, 0)
        : null;
      const foot = node("div", "", "cockpit-card-foot");
      const linkRow = node("div", "", "cockpit-card-link-row");
      linkRow.append(
        node("span", (s.used == null ? "N/A" : size(s.used)) + " / " + (s.capacity == null ? "N/A" : size(s.capacity))),
        node("strong", netBytes == null ? "N/A" : size(netBytes)),
      );
      foot.append(linkRow);
      card.append(foot);
      grid.append(card);
    });

    el("lab-users-panel").hidden = !selectedLab;
    el("lab-users-title").textContent =
      d.disks.find((s) => s.lab === selectedLab)?.title || "";
  }
  function render() {
    if (!data?.latest) {
      [
        "monitor-headroom",
        "monitor-overview",
        "monitor-gpu-rack",
        "monitor-labs",
        "monitor-users",
        "network-ranking",
      ].forEach((id) => el(id)?.replaceChildren());
      el("monitor-health").textContent = t("기록 없음");
      el("monitor-time").textContent = "—";
      el("monitor-error").textContent = t("선택한 기간에 기록이 없습니다.");
      el("history-summary").textContent = "";
      if (el("monitor-detail").open) el("monitor-detail").close();
      return;
    }
    const d = data.latest,
      h = data.history,
      stale = !data.historical && Date.now() / 1000 - d.ts > 180;
    el("history-summary").textContent =
      t(
        data.archive
          ? "15분 요약 포함 · 네트워크 합계와 최고 전송률 유지"
          : "1분 상세 기록",
      ) +
      " · " +
      t("기록 보관") +
      " " +
      data.settings.archive_days +
      " " +
      t("일");
    const loc = document.documentElement.lang === "en" ? "en-US" : "ko-KR";
    el("monitor-time").textContent = new Date(d.ts * 1000).toLocaleString(loc);
    el("monitor-error").textContent = stale
      ? t("수집 지연 · 마지막 기록 표시")
      : "";
    const warning = issues();
    el("monitor-health").textContent = t(
      data.historical
        ? "과거 기록"
        : stale
          ? "수집 지연"
          : warning.length
            ? "확인 필요"
            : "모든 환경 실행 중",
    );
    el("monitor-health").classList.toggle(
      "attention",
      stale || !!warning.length,
    );

    renderHeadroom();

    const avgGpuPct =
      d.gpus.length && d.gpus.every((g) => g.util != null)
        ? sumKnown(d.gpus.map((g) => g.util)) / d.gpus.length
        : null;
    const totalVramUsedGb = d.gpus.reduce((n, g) => n + (g.used || 0) / 1024, 0);
    const totalVramCapGb = d.gpus.reduce((n, g) => n + (g.total || 0) / 1024, 0);
    const totalPowerW = d.gpus.reduce((n, g) => n + (g.power || 0), 0);
    const vramRatio = totalVramCapGb > 0 ? (totalVramUsedGb / totalVramCapGb) * 100 : null;

    const memTotalGib = (d.memory_total || 0) / 1073741824;
    const memUsedGib = (d.memory_used || 0) / 1073741824;
    const memPct = memTotalGib > 0 ? (memUsedGib / memTotalGib) * 100 : null;

    const labDiskUsed = sumKnown(d.disks.map((s) => s.used));
    const labDiskCap = sumKnown(d.disks.map((s) => s.capacity));
    const hs = data.host_summary || {};
    const diskGaugePct =
      hs.pool_total_bytes && labDiskCap != null
        ? (labDiskCap / hs.pool_total_bytes) * 100
        : labDiskCap && labDiskUsed != null
          ? (labDiskUsed / labDiskCap) * 100
          : null;

    const panels = [
      {
        name: "평균 GPU 사용률",
        key: "gpu",
        color: colors[1],
        max: 100,
        pct: avgGpuPct,
        innerPct: vramRatio,
        centerMain: avgGpuPct == null ? "N/A" : avgGpuPct.toFixed(0) + "%",
        centerSub: d.gpus.length + "× GPU",
        detailTop: "VRAM " + totalVramUsedGb.toFixed(0) + " / " + totalVramCapGb.toFixed(0) + " GB",
        detailSub: t("여유") + " " + Math.max(0, totalVramCapGb - totalVramUsedGb).toFixed(0) + " GB · " + totalPowerW.toFixed(0) + " W",
        format: (v) => v.toFixed(1) + "%",
        values: h.map((p) => ({ ts: p.ts, value: p.gpu })),
      },
      {
        name: "서버 CPU 사용률",
        key: "cpu",
        color: colors[0],
        max: 100,
        pct: d.cpu_util,
        centerMain: d.cpu_util == null ? "N/A" : d.cpu_util.toFixed(1) + "%",
        centerSub: (d.cpu_count || 0) + " " + t("코어"),
        detailTop: t("사용량") + " " + ((d.cpu_util || 0) * (d.cpu_count || 0) / 100).toFixed(1) + " / " + (d.cpu_count || 0),
        detailSub: t("여유") + " " + ((100 - (d.cpu_util || 0)) * (d.cpu_count || 0) / 100).toFixed(1) + " " + t("코어"),
        format: (v) => v.toFixed(1) + "%",
        values: h.map((p) => ({ ts: p.ts, value: p.cpu_util })),
      },
      {
        name: "시스템 메모리",
        key: "memory",
        color: colors[2],
        max: memTotalGib,
        pct: memPct,
        centerMain: memPct == null ? "N/A" : memPct.toFixed(1) + "%",
        centerSub: memTotalGib.toFixed(0) + " GiB",
        detailTop: memUsedGib.toFixed(1) + " / " + memTotalGib.toFixed(0) + " GiB",
        detailSub: t("여유") + " " + Math.max(0, memTotalGib - memUsedGib).toFixed(0) + " GiB",
        format: (v) => v.toFixed(1) + " GiB",
        values: h.map((p) => ({ ts: p.ts, value: p.memory / 1073741824 })),
      },
      {
        name: "연구실 디스크 · 네트워크",
        key: "network",
        color: colors[3],
        pct: diskGaugePct,
        innerPct: hs.pool_total_bytes && labDiskUsed != null ? (labDiskUsed / hs.pool_total_bytes) * 100 : null,
        centerMain: diskGaugePct == null ? "N/A" : diskGaugePct.toFixed(0) + "%",
        centerSub: hs.pool_total_bytes ? size(hs.pool_total_bytes) : t("디스크"),
        detailTop: t("사용량") + " " + (labDiskUsed == null ? "N/A" : size(labDiskUsed)) + " / " + (labDiskCap == null ? "N/A" : size(labDiskCap)),
        detailSub: hs.pool_free_bytes ? t("서버 여유") + " " + size(hs.pool_free_bytes) : "",
        format: (v) => size(v) + "/s",
        values: h.map((p) => ({
          ts: p.ts,
          value:
            totals(p, "rx") == null ? null : totals(p, "rx") + totals(p, "tx"),
        })),
      },
    ];

    const overview = el("monitor-overview");
    overview.replaceChildren();
    panels.forEach((p) => {
      const card = node("section", "", "cockpit-card");
      const head = node("div", "", "cockpit-card-head");
      const button = node("button", t(p.name), "metric-title");
      button.type = "button";
      button.onclick = () => open(p.key === "network" ? "network" : "hardware");
      const st = statusForPct(p.pct);
      head.append(button, node("span", t(st.label), "sig-badge " + st.badge));
      card.append(head);

      card.append(
        buildGaugeSvg(p.pct, p.centerMain, p.centerSub, { innerPct: p.innerPct }),
      );
      const figs = node("div", "", "cockpit-dial-figures");
      figs.append(node("strong", p.detailTop));
      if (p.detailSub) figs.append(node("small", p.detailSub));
      card.append(figs);

      series(card, t(p.name), p.values, p.format, p.color, p.max);
      overview.append(card);
    });

    renderGpuRack();
    renderLabs();

    const users = el("monitor-users");
    users.replaceChildren();
    d.accounts
      .filter((a) => a.lab === selectedLab)
      .forEach((a) => {
        const card = node("article", "", "account-tile");
        const button = node("button", "", "account-select");
        button.type = "button";
        const status = node(
          "span",
          "",
          "presence " + (a.running ? "online" : "offline"),
        );
        status.setAttribute("aria-label", t(a.running ? "실행 중" : "정지"));
        // Account ID ONLY in summary header
        button.append(
          status,
          node("strong", a.user),
          node("span", "›", "account-arrow"),
        );
        button.onclick = () => open("account", a.lab + "/" + a.user);
        card.append(button);
        const p = h.map((row) => {
          const match = row.accounts.find((u) => u.user === a.user && u.lab === a.lab);
          return {
            ts: row.ts,
            value: match?.cpu == null ? null : match.cpu / 100,
          };
        });
        series(
          card,
          a.user + " · CPU",
          p,
          (v) => v.toFixed(2) + " " + t("코어"),
          a.running ? colors[0] : "#9cabb3",
          d.cpu_count,
        );
        card.append(node("span", t("CPU 사용 추이"), "metric-caption"));
        meter(card, "메모리", memoryBytes(a.memory), d.memory_total, size);
        const rates = a.rates;
        const traffic = node("button", t("네트워크 상세"), "secondary");
        V.hint(
          traffic,
          t("수신") +
            " " +
            size(rates?.rx) +
            "/s · " +
            t("송신") +
            " " +
            size(rates?.tx) +
            "/s",
        );
        traffic.onclick = () => open("network-account", a.lab + "/" + a.user);
        card.append(traffic);
        users.append(card);
      });
    renderNetwork(el("network-ranking"), selectedLab);
    if (el("monitor-detail").open) renderDetail();
  }
  function renderNetwork(target, lab = null) {
    target.replaceChildren();
    const usage = (data.network_usage || []).filter(
      (a) => lab === null || a.lab === lab,
    );
    const max = Math.max(1, ...usage.map((a) => a.rx + a.tx));
    usage.forEach((a) => {
      const button = node("button", "", "network-account");
      button.type = "button";
      button.append(node("strong", a.user));
      const rxW = (100 * a.rx) / max;
      const txW = (100 * a.tx) / max;
      const bar = V.svg("svg", {
        class: "network-bar-svg",
        viewBox: "0 0 100 14",
        preserveAspectRatio: "none",
        "aria-hidden": "true",
      });
      bar.append(
        V.svg("rect", { class: "net-svg-bg", x: 0, y: 0, width: 100, height: 14, rx: 5 }),
        V.svg("rect", { class: "net-svg-rx", x: 0, y: 0, width: rxW.toFixed(2), height: 14 }),
        V.svg("rect", { class: "net-svg-tx", x: rxW.toFixed(2), y: 0, width: txW.toFixed(2), height: 14 }),
      );
      button.append(bar, node("span", a.seconds ? "›" : "N/A"));
      V.hint(
        button,
        () =>
          a.user +
          "\n" +
          t("수신") +
          " " +
          (a.seconds ? size(a.rx) : "N/A") +
          " · " +
          t("송신") +
          " " +
          (a.seconds ? size(a.tx) : "N/A"),
      );
      button.onclick = () => open("network-account", a.lab + "/" + a.user);
      target.append(button);
    });
  }
  function networkDetail(body, a) {
    const list = node("dl", "", "detail-values");
    row(list, "기간 수신량", a.seconds ? size(a.rx) : "N/A");
    row(list, "기간 송신량", a.seconds ? size(a.tx) : "N/A");
    row(
      list,
      "수신 / 송신 패킷",
      a.seconds
        ? a.rx_packets.toLocaleString() + " / " + a.tx_packets.toLocaleString()
        : "N/A",
    );
    row(list, "최고 전송률", a.seconds ? size(a.peak) + "/s" : "N/A");
    row(
      list,
      "최고 전송 시점",
      a.peak_ts ? new Date(a.peak_ts * 1000).toLocaleString() : "N/A",
    );
    row(list, "집계 시간", (a.seconds / 3600).toFixed(2) + " h");
    row(
      list,
      "패킷 오류 / 드롭",
      a.seconds ? a.errors + " / " + a.drops : "N/A",
    );
    body.append(
      list,
      node(
        "p",
        t(
          "확인된 연속 기록만 합산합니다. 재시작·수집 공백은 제외하며 최고 전송률은 수집 간격의 평균입니다.",
        ),
        "muted",
      ),
    );
    const grid = node("div", "", "network-detail-charts");
    const scale = Math.max(
      1,
      ...data.history.flatMap((p) => {
        const u = p.accounts.find((u) => u.user === a.user && u.lab === a.lab);
        return [u?.rx || 0, u?.tx || 0];
      }),
    );
    ["rx", "tx"].forEach((key, i) => {
      const card = node("section", "", "metric-card");
      card.append(node("h3", t(key === "rx" ? "수신" : "송신")));
      series(
        card,
        t(key === "rx" ? "수신" : "송신"),
        data.history.map((p) => ({
          ts: p.ts,
          value:
            p.accounts.find((u) => u.user === a.user && u.lab === a.lab)?.[
              key
            ] ?? null,
        })),
        (v) => size(v) + "/s",
        colors[i],
        scale,
      );
      grid.append(card);
    });
    body.append(grid, node("h3", t("패킷 오류·드롭 기록")));
    if (!a.incidents.length)
      body.append(
        node("p", t(a.seconds ? "선택 기간 내 기록 없음" : "수집 대기")),
      );
    [...a.incidents]
      .reverse()
      .forEach((e) =>
        body.append(
          node(
            "p",
            new Date(e.ts * 1000).toLocaleString() +
              " · " +
              t("오류") +
              " " +
              e.errors +
              " · " +
              t("드롭") +
              " " +
              e.drops,
          ),
        ),
      );
  }
  function open(kind, user = null) {
    dialogKind = kind;
    selected = user;
    V.hide();
    renderDetail();
    if (!el("monitor-detail").open) el("monitor-detail").showModal();
  }
  function row(list, label, value) {
    const box = node("div", "", "detail-value");
    box.append(node("dt", t(label)), node("dd", value));
    list.append(box);
  }
  function renderDetail() {
    if (!data?.latest) return;
    const body = el("detail-body");
    body.replaceChildren();
    const d = data.latest;
    let title = "";
    if (dialogKind === "network") {
      title = t("네트워크 사용량");
      renderNetwork(body);
    } else if (dialogKind === "network-account") {
      const a = (data.network_usage || []).find(
        (a) => a.lab + "/" + a.user === selected,
      );
      if (!a) return;
      title = a.user + " · " + t("네트워크");
      networkDetail(body, a);
    } else if (dialogKind === "account") {
      const a = d.accounts.find((a) => a.lab + "/" + a.user === selected);
      if (!a) return;
      title = a.user;
      const list = node("dl", "", "detail-values");
      row(list, "상태", t(a.running ? "실행 중" : "정지"));
      row(
        list,
        "CPU 사용량",
        a.cpu == null ? "N/A" : (a.cpu / 100).toFixed(2) + " " + t("코어"),
      );
      row(list, "메모리", a.memory || "N/A");
      row(list, "GPU", t("연구실 공동 사용 · 사용자별 미집계"));
      row(list, "연구실", d.disks.find((s) => s.lab === a.lab)?.title || a.lab);
      row(
        list,
        "수신 / 송신",
        a.rates ? size(a.rates.rx) + "/s / " + size(a.rates.tx) + "/s" : "N/A",
      );
      row(
        list,
        "패킷 / 초",
        a.rates ? (a.rates.rx_packets + a.rates.tx_packets).toFixed(1) : "N/A",
      );
      row(list, "디스크 읽기 / 쓰기", a.block_io || "N/A");
      row(
        list,
        "패킷 오류 / 드롭",
        a.network ? a.network.errors + " / " + a.network.drops : "N/A",
      );
      body.append(
        list,
        node("h3", t("주요 프로세스")),
        node(
          "p",
          a.processes.map((p) => p.name + " ×" + p.count).join(" · ") || "—",
        ),
      );
      const link = node("a", t("계정 관리"), "button");
      link.href = "/labs/" + encodeURIComponent(a.lab) + "/accounts#account-" + encodeURIComponent(a.user);
      body.append(link);
      const filesLink = node("a", t("저장공간 분석"), "button secondary");
      filesLink.href = "/labs/" + encodeURIComponent(a.lab) + "/files";
      body.append(filesLink);
      const net = node("button", t("네트워크 상세"), "secondary");
      net.onclick = () => open("network-account", a.lab + "/" + a.user);
      body.append(net);
      body.append(node("h3", t("CPU 사용 추이")));
      series(
        body,
        "CPU",
        data.history.map((p) => {
          const match = p.accounts.find((u) => u.lab + "/" + u.user === selected);
          return {
            ts: p.ts,
            value: match?.cpu == null ? null : match.cpu / 100,
          };
        }),
        (v) => v.toFixed(2) + " " + t("코어"),
        colors[0],
      );
    } else if (dialogKind === "hardware") {
      title = t("하드웨어 상태");
      const grid = node("div", "", "monitor-hardware");
      d.gpus.forEach((g) => {
        const box = node("div");
        box.append(
          node("strong", "GPU " + g.index),
          node(
            "span",
            (g.util ?? "N/A") + "% · " + (g.temperature ?? "N/A") + " °C",
          ),
          node("span", (g.used ?? "N/A") + " / " + (g.total ?? "N/A") + " MiB"),
          node("span", (g.power ?? "N/A") + " W"),
        );
        grid.append(box);
      });
      d.disks.forEach((s) => {
        const box = node("div");
        box.append(
          node("strong", s.title),
          node(
            "span",
            s.mounted
              ? size(s.used) + " / " + size(s.capacity)
              : t("저장공간 연결 끊김"),
          ),
        );
        grid.append(box);
      });
      body.append(grid);
    } else if (dialogKind === "events") {
      title = t("상태 변경 기록");
      const names = {
        started: "환경 시작",
        stopped: "환경 정지",
        restarted: "환경 재시작",
        mount_missing: "저장공간 연결 끊김",
        storage_high: "저장공간 90% 이상",
      };
      data.events.forEach((e) =>
        body.append(
          node(
            "p",
            new Date(e.ts * 1000).toLocaleString() +
              " · " +
              e.subject +
              " · " +
              t(names[e.kind] || e.kind),
          ),
        ),
      );
      if (!data.events.length) body.append(node("p", t("상태 변경 기록 없음")));
    } else if (dialogKind === "health") {
      title = t("상태 확인");
      const messages = issues();
      body.append(
        ...(messages.length ? messages : [t("모든 환경 실행 중")]).map((s) =>
          node("p", s),
        ),
      );
    } else {
      title = t("집계 기준");
      body.append(
        node(
          "p",
          t("상세 기록") +
            " " +
            data.settings.raw_days +
            " " +
            t("일") +
            " · " +
            t("전체 보관 기간") +
            " " +
            data.settings.archive_days +
            " " +
            t("일"),
        ),
        node(
          "p",
          t(
            "CPU 사용량은 논리 CPU 개수로 환산합니다. 송수신량은 컨테이너 네트워크 인터페이스 기준이며 패킷 본문·접속 목적지·명령 인자·파일 내용은 수집하지 않습니다. 실행 상태는 외부 SSH 접속 성공 여부를 뜻하지 않습니다. 프로세스 이름만으로 연구 내용이나 작업 목적을 판단하지 않습니다.",
          ),
        ),
      );
    }
    el("detail-title").textContent = title;
  }
  el("detail-close").onclick = () => el("monitor-detail").close();
  el("lab-users-close").onclick = () => {
    selectedLab = null;
    el("lab-users-panel").hidden = true;
    el("monitor-labs")?.querySelectorAll(".selected").forEach((n) => n.classList.remove("selected"));
  };
  el("monitor-detail").addEventListener("close", V.hide);
  el("monitor-hardware-open").onclick = () => open("hardware");
  el("monitor-events-open").onclick = () => open("events");
  el("monitor-info-open").onclick = () => open("info");
  el("monitor-health").onclick = () => data?.latest && open("health");
  function schedule() {
    clearTimeout(timer);
    if (el("monitor-window").value === "custom") return;
    timer = setTimeout(() => (document.hidden ? schedule() : load()), 60000);
  }
  let loadSequence = 0;
  async function load() {
    const sequence = ++loadSequence;
    try {
      let query = "hours=" + el("monitor-window").value;
      if (el("monitor-window").value === "custom") {
        const start = new Date(el("history-start").value + "T00:00:00");
        const end = new Date(el("history-end").value + "T00:00:00");
        end.setDate(end.getDate() + 1);
        if (
          !Number.isFinite(+start) ||
          !Number.isFinite(+end) ||
          end <= start ||
          end - start > 31 * 86400000
        )
          throw Error(t("날짜 범위는 최대 31일입니다."));
        query =
          "start=" +
          Math.floor(+start / 1000) +
          "&end=" +
          Math.floor(+end / 1000);
      }
      const r = await fetch("/api/telemetry?" + query);
      if (!r.ok) throw Error(t("지표를 불러오지 못했습니다."));
      const next = await r.json();
      if (sequence !== loadSequence) return;
      data = next;
      render();
    } catch (e) {
      el("monitor-error").textContent = e.message;
    } finally {
      schedule();
    }
  }
  el("monitor-window").onchange = () => {
    clearTimeout(timer);
    el("history-range").hidden = el("monitor-window").value !== "custom";
    load();
  };
  const today = new Date(),
    dateValue = new Date(+today - today.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 10);
  ["history-start", "history-end"].forEach((id) => {
    el(id).value = dateValue;
    el(id).max = dateValue;
  });
  el("history-range").onsubmit = (e) => {
    e.preventDefault();
    load();
  };
  el("retention-open").onclick = () => {
    el("raw-days").value = data?.settings?.raw_days || 7;
    el("archive-days").value = data?.settings?.archive_days || 90;
    el("retention-ack").checked = false;
    el("retention-result").textContent = "";
    el("retention-dialog").showModal();
  };
  el("retention-close").onclick = () => el("retention-dialog").close();
  el("retention-form").onsubmit = async (e) => {
    e.preventDefault();
    if (!el("retention-ack").checked) {
      el("retention-result").textContent = t("자동 삭제 안내를 확인해 주세요.");
      return;
    }
    try {
      const r = await fetch("/api/telemetry/retention", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": el("retention-form").elements.csrf.value,
        },
        body: JSON.stringify({
          raw_days: Number(el("raw-days").value),
          archive_days: Number(el("archive-days").value),
        }),
      });
      if (!r.ok) throw Error(t("저장 실패"));
      const cfg = await r.json();
      if (data) data.settings = cfg;
      el("retention-result").textContent = t(
        "저장되었습니다. 다음 수집부터 적용됩니다.",
      );
    } catch (e) {
      el("retention-result").textContent = e.message;
    }
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && el("monitor-window").value !== "custom") {
      clearTimeout(timer);
      load();
    }
  });
  load();
})();
