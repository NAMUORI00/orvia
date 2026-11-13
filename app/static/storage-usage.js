(async () => {
  const root = document.getElementById("usage-view");
  if (!root) return;
  const messages = await fetch("/api/translations").then((r) => r.json()),
    t = (s) => messages[s] || s,
    V = window.OrviaViz;
  const el = (id) => document.getElementById(id),
    colors = ["#218878", "#5b88bd", "#9872b4", "#cb984d", "#699a9e", "#b36c80"];
  const size = (n) =>
    n >= 1e12
      ? (n / 1e12).toFixed(2) + " TB"
      : n >= 1e9
        ? (n / 1e9).toFixed(1) + " GB"
        : n >= 1e6
          ? (n / 1e6).toFixed(1) + " MB"
          : (n / 1024).toFixed(1) + " KiB";
  const button = (label, fn) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "secondary";
    b.textContent = label;
    b.onclick = fn;
    return b;
  };
  let path = "",
    parent = "",
    timer,
    current;
  function navigate(p) {
    path = p;
    clearTimeout(timer);
    load();
  }
  function detail() {
    if (!current) return;
    const list = el("usage-detail-values");
    list.replaceChildren();
    for (const [k, v] of [
      ["전체 용량", size(current.capacity)],
      ["사용량", size(current.used)],
      ["여유 공간", size(Math.max(0, current.capacity - current.used))],
      ["서버 저장 경로", current.root],
    ]) {
      const wrap = document.createElement("div");
      wrap.className = "detail-value";
      const label = document.createElement("dt");
      label.textContent = t(k);
      const value = document.createElement("dd");
      value.textContent = v;
      wrap.append(label, value);
      list.append(wrap);
    }
    V.hide();
    el("usage-detail").showModal();
  }
  el("usage-detail-open").onclick = detail;
  el("usage-detail-close").onclick = () => el("usage-detail").close();
  el("usage-detail").addEventListener("close", V.hide);
  el("usage-up").onclick = () => navigate(parent);
  function render(d) {
    current = d;
    parent = d.parent;
    el("usage-time").textContent = new Date(
      d.scanned_at * 1000,
    ).toLocaleString();
    const ratio = Math.max(0, Math.min(1, d.used / Math.max(1, d.capacity))),
      gauge = el("usage-gauge");
    gauge.replaceChildren();
    gauge.append(
      V.svg("circle", {
        cx: 90,
        cy: 90,
        r: 65,
        fill: "none",
        stroke: "#e7eef0",
        "stroke-width": 15,
      }),
    );
    const arc = V.svg("circle", {
      cx: 90,
      cy: 90,
      r: 65,
      fill: "none",
      stroke: ratio >= 0.9 ? "#cb984d" : colors[0],
      "stroke-width": 15,
      "stroke-dasharray": ratio * 408.4 + " 408.4",
      transform: "rotate(-90 90 90)",
      "stroke-linecap": "round",
    });
    gauge.append(arc);
    const caption = V.svg("text", {
      x: 90,
      y: 95,
      "text-anchor": "middle",
      fill: "#31505a",
      "font-size": 16,
    });
    caption.textContent = t(ratio >= 0.9 ? "용량 확인" : "사용 공간");
    gauge.append(caption);
    const gaugeText =
      t("사용량") +
      " " +
      size(d.used) +
      " / " +
      size(d.capacity) +
      " · " +
      (ratio * 100).toFixed(1) +
      "%";
    V.hint(gauge, gaugeText);
    gauge.onclick = (e) => V.show(gaugeText, gauge, e);
    const chart = el("usage-allocation");
    chart.replaceChildren();
    chart.append(
      V.svg("rect", {
        x: 0,
        y: 0,
        width: 1000,
        height: 100,
        fill: "#e7eef0",
        rx: 8,
      }),
    );
    const accounts = el("usage-accounts");
    accounts.replaceChildren();
    let x = 0;
    d.accounts.forEach((a, i) => {
      const width = Math.min(1000 - x, (a.bytes / Math.max(1, d.used)) * 1000),
        color = colors[i % colors.length],
        info =
          a.name +
          "\n" +
          size(a.bytes) +
          " · " +
          ((a.bytes / Math.max(1, d.used)) * 100).toFixed(1) +
          "%";
      const rect = V.svg("rect", {
        x,
        y: 0,
        width,
        height: 100,
        fill: color,
        tabindex: 0,
        role: "button",
        "aria-label": a.name,
      });
      V.hint(rect, info);
      rect.onclick = (e) => {
        V.show(info, rect, e);
        navigate(a.path);
      };
      rect.onkeydown = (e) => {
        if (["Enter", " "].includes(e.key)) {
          e.preventDefault();
          navigate(a.path);
        }
      };
      chart.append(rect);
      x += width;
      const b = button(a.name, (e) => {
        V.show(info, b, e);
        navigate(a.path);
      });
      const dot = V.svg("svg", {
        width: 12,
        height: 12,
        viewBox: "0 0 12 12",
        "aria-hidden": "true",
      });
      dot.append(V.svg("circle", { cx: 6, cy: 6, r: 5, fill: color }));
      b.prepend(dot);
      V.hint(b, info);
      accounts.append(b);
    });
    const other = Math.max(
        0,
        d.used - d.accounts.reduce((n, a) => n + a.bytes, 0),
      ),
      otherLabel = t(d.partial ? "미집계·기타" : "기타·관리 영역");
    const segment = V.svg("rect", {
      x,
      y: 0,
      width: Math.min(1000 - x, (other / Math.max(1, d.used)) * 1000),
      height: 100,
      fill: "#9baab6",
      tabindex: 0,
      "aria-label": otherLabel,
    });
    V.hint(segment, otherLabel + " · " + size(other));
    chart.append(segment);
    el("usage-path-panel").hidden = !path;
    el("usage-path").textContent = path;
    el("usage-host").textContent = d.root + (path ? "/" + path : "");
    const list = el("usage-paths");
    list.replaceChildren();
    d.entries.forEach((a, i) => {
      const info =
        a.name +
        "\n" +
        size(a.bytes) +
        " · " +
        ((a.bytes / Math.max(1, d.selected)) * 100).toFixed(1) +
        "%";
      const b = button("", (e) => {
        V.show(info, b, e);
        if (a.directory) navigate(a.path);
      });
      b.className = "usage-path-row";
      const title = document.createElement("strong");
      title.textContent = (a.directory ? "▰ " : "▤ ") + a.name;
      const bar = V.svg("svg", {
        viewBox: "0 0 500 12",
        preserveAspectRatio: "none",
        "aria-hidden": "true",
      });
      bar.append(
        V.svg("rect", {
          x: 0,
          y: 0,
          width: 500,
          height: 12,
          fill: "#edf2f5",
          rx: 6,
        }),
        V.svg("rect", {
          x: 0,
          y: 0,
          width: Math.min(500, (500 * a.bytes) / Math.max(1, d.selected)),
          height: 12,
          fill: colors[i % colors.length],
          rx: 6,
        }),
      );
      b.append(title, bar);
      V.hint(b, info);
      list.append(b);
    });
    el("usage-state").textContent = t(
      d.partial
        ? "부분 집계 · 일부 항목을 집계하지 못했습니다."
        : d.refreshing
          ? "이전 집계 표시 · 갱신 중"
          : "집계 완료",
    );
    if (path && !d.entries.length)
      el("usage-state").textContent = t(
        "세부 경로 집계는 최대 4단계까지 제공합니다.",
      );
  }
  function schedule(delay) {
    timer = setTimeout(
      () => (document.hidden ? schedule(60000) : load()),
      delay,
    );
  }
  async function load() {
    let delay = 60000;
    try {
      const r = await fetch(
          "/api/storage-usage/" +
            encodeURIComponent(root.dataset.lab) +
            "?path=" +
            encodeURIComponent(path),
        ),
        d = await r.json();
      if (!r.ok) throw Error(d.error);
      if (d.state !== "ready") {
        el("usage-state").textContent = t(
          d.state === "queued"
            ? "다른 저장공간 집계 대기"
            : d.state === "unavailable"
              ? "집계 지연 · 잠시 후 다시 확인하세요."
              : "저장공간 집계 중",
        );
        delay = d.state === "unavailable" ? 60000 : 4000;
        return;
      }
      render(d);
      if (d.refreshing) delay = 4000;
    } catch (e) {
      el("usage-state").textContent = e.message;
    } finally {
      schedule(delay);
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
