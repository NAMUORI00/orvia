(async () => {
  const messages = await fetch("/api/translations").then((r) => r.json());
  const t = (s) => messages[s] || s;
  const el = (id) => document.getElementById(id),
    text = (tag, value) => {
      const e = document.createElement(tag);
      e.textContent = value;
      return e;
    };
  const size = (n) =>
    n == null
      ? "N/A"
      : n >= 1e9
        ? (n / 1e9).toFixed(1) + " GB"
        : n >= 1e6
          ? (n / 1e6).toFixed(1) + " MB"
          : (n / 1024).toFixed(1) + " KiB";
  let selected = null,
    data = null,
    timer;
  function chart(id, values, label, unit) {
    const node = el(id);
    node.replaceChildren();
    const valid = values.filter((v) => v != null);
    if (!valid.length) {
      el(label).textContent = t("수집 대기");
      return;
    }
    const peak = Math.max(...valid),
      max = Math.max(1, peak);
    let segment = [];
    const flush = () => {
      if (segment.length) {
        const p = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "polyline",
        );
        p.setAttribute("points", segment.join(" "));
        p.setAttribute("fill", "none");
        p.setAttribute("stroke", "#218878");
        p.setAttribute("stroke-width", "3");
        node.append(p);
        segment = [];
      }
    };
    values.forEach((v, i) => {
      if (v == null) {
        flush();
        return;
      }
      segment.push(
        10 +
          (i * 580) / Math.max(1, values.length - 1) +
          "," +
          (140 - (v / max) * 125),
      );
    });
    flush();
    const last = values
      .map((v, i) => ({ v, i }))
      .filter((p) => p.v != null)
      .pop();
    if (last) {
      const point = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "circle",
      );
      point.setAttribute(
        "cx",
        10 + (last.i * 580) / Math.max(1, values.length - 1),
      );
      point.setAttribute("cy", 140 - (last.v / max) * 125);
      point.setAttribute("r", "4");
      point.setAttribute("fill", "#218878");
      node.append(point);
    }
    el(label).textContent =
      t("최대") +
      " " +
      peak.toFixed(2) +
      " " +
      unit +
      " · " +
      el("monitor-window").selectedOptions[0].textContent;
  }
  function render() {
    if (!data || !data.latest) return;
    const d = data.latest;
    el("monitor-time").textContent = new Date(d.ts * 1000).toLocaleString();
    el("monitor-error").textContent =
      Date.now() / 1000 - d.ts > 180 ? t("수집 지연 · 마지막 기록 표시") : "";
    const summary = el("monitor-summary");
    summary.replaceChildren();
    for (const [key, value] of [
      [
        t("실행 중"),
        d.accounts.filter((a) => a.running).length + " / " + d.accounts.length,
      ],
      [
        t("시스템 메모리"),
        (d.memory_used / 1073741824).toFixed(1) +
          " / " +
          (d.memory_total / 1073741824).toFixed(0) +
          " GiB",
      ],
      [
        t("평균 GPU 사용률"),
        (
          d.gpus.reduce((v, g) => v + (g.util || 0), 0) /
          Math.max(1, d.gpus.length)
        ).toFixed(1) + "%",
      ],
      [
        t("서버 CPU 사용률"),
        d.cpu_util == null ? "N/A" : d.cpu_util.toFixed(1) + "%",
      ],
    ]) {
      const box = text("div", "");
      box.append(text("span", key), text("strong", value));
      summary.append(box);
    }
    const users = el("monitor-users");
    users.replaceChildren();
    d.accounts.forEach((a) => {
      const row = document.createElement("tr");
      if (selected === a.user) row.className = "selected";
      const cell = document.createElement("td"),
        b = text("button", a.user);
      b.className = "secondary";
      b.onclick = () => {
        selected = a.user;
        render();
      };
      cell.append(b);
      row.append(cell);
      for (const value of [
        t(a.running ? "실행 중" : "정지"),
        a.cpu == null ? "N/A" : (a.cpu / 100).toFixed(2) + " " + t("코어"),
        a.memory || "N/A",
        a.rates ? size(a.rates.rx) + "/s / " + size(a.rates.tx) + "/s" : "N/A",
        a.rates ? (a.rates.rx_packets + a.rates.tx_packets).toFixed(1) : "N/A",
        a.processes
          .slice(0, 3)
          .map((p) => p.name + (p.count > 1 ? " ×" + p.count : ""))
          .join(" · ") +
          (a.processes.length > 3 ? " +" + (a.processes.length - 3) : "") ||
          "—",
      ])
        row.append(text("td", value));
      users.append(row);
    });
    const detail = el("monitor-account");
    detail.replaceChildren();
    detail.hidden = !selected;
    const account = d.accounts.find((a) => a.user === selected);
    if (account) {
      detail.append(
        text("h3", account.user),
        text(
          "p",
          account.processes.map((p) => p.name + " ×" + p.count).join(" · "),
        ),
      );
      const net = account.network || {};
      detail.append(
        text(
          "p",
          t("누적 수신 / 송신") + " · " + size(net.rx) + " / " + size(net.tx),
        ),
        text(
          "p",
          t("패킷 오류 / 드롭") +
            " · " +
            (net.errors ?? "N/A") +
            " / " +
            (net.drops ?? "N/A"),
        ),
        text(
          "p",
          t("디스크 읽기 / 쓰기") + " · " + (account.block_io || "N/A"),
        ),
      );
      const link = text("a", t("저장공간 분석"));
      link.href = "/labs/" + encodeURIComponent(account.lab) + "/files";
      detail.append(link);
    }
    const chosen = (h) =>
      h.accounts.filter((a) => !selected || a.user === selected);
    const totals = (h, f) => {
      const a = chosen(h)
        .map(f)
        .filter((v) => v != null);
      return a.length ? a.reduce((v, n) => v + n, 0) : null;
    };
    chart(
      "cpu-history",
      data.history.map((h) =>
        totals(h, (a) => (a.cpu == null ? null : a.cpu / 100)),
      ),
      "cpu-chart-range",
      t("코어"),
    );
    chart(
      "net-history",
      data.history.map((h) =>
        totals(h, (a) => (a.rx == null ? null : (a.rx + a.tx) / 1024)),
      ),
      "net-chart-range",
      "KiB/s",
    );
    el("cpu-chart-title").textContent =
      (selected ? selected + " · " : "") + t("CPU 사용 추이");
    chart(
      "gpu-history",
      data.history.map((h) => h.gpu),
      "gpu-chart-range",
      "%",
    );
    chart(
      "memory-history",
      data.history.map((h) => h.memory / 1073741824),
      "memory-chart-range",
      "GiB",
    );
    const hw = el("monitor-hardware");
    hw.replaceChildren();
    d.gpus.forEach((g) => {
      const box = text("div", "");
      box.append(
        text("strong", "GPU " + g.index),
        text(
          "span",
          (g.util ?? "N/A") + "% · " + (g.temperature ?? "N/A") + " °C",
        ),
        text("span", (g.used ?? "N/A") + " / " + (g.total ?? "N/A") + " MiB"),
        text("span", (g.power ?? "N/A") + " W"),
      );
      hw.append(box);
    });
    d.disks.forEach((s) => {
      const box = text("div", "");
      box.append(
        text("strong", s.title),
        text(
          "span",
          s.mounted
            ? size(s.used) + " / " + size(s.capacity)
            : t("저장공간 연결 끊김"),
        ),
      );
      hw.append(box);
    });
    const events = el("monitor-events");
    events.replaceChildren();
    const names = {
      started: "환경 시작",
      stopped: "환경 정지",
      restarted: "환경 재시작",
      mount_missing: "저장공간 연결 끊김",
      storage_high: "저장공간 90% 이상",
    };
    data.events.forEach((e) =>
      events.append(
        text(
          "p",
          new Date(e.ts * 1000).toLocaleString() +
            " · " +
            e.subject +
            " · " +
            t(names[e.kind] || e.kind),
        ),
      ),
    );
    if (!data.events.length) events.append(text("p", t("상태 변경 기록 없음")));
  }
  function schedule() {
    timer = setTimeout(() => {
      if (document.hidden) schedule();
      else load();
    }, 60000);
  }
  el("monitor-window").onchange = () => {
    clearTimeout(timer);
    load();
  };
  el("monitor-reset").onclick = () => {
    selected = null;
    render();
  };
  async function load() {
    try {
      const r = await fetch(
        "/api/telemetry?hours=" + el("monitor-window").value,
      );
      if (!r.ok) throw Error(t("지표를 불러오지 못했습니다."));
      data = await r.json();
      render();
    } catch (e) {
      el("monitor-error").textContent = e.message;
    } finally {
      schedule();
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      load();
    }
  });
  load();
})();
