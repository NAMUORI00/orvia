(async () => {
  const root = document.getElementById("usage-view");
  if (!root) return;
  const messages = await fetch("/api/translations").then((r) => r.json());
  const t = (s) => messages[s] || s;
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
  const svg = (tag, attrs) => {
    const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  };
  let path = "",
    parent = "",
    timer;
  const button = (label, action) => {
    const e = document.createElement("button");
    e.type = "button";
    e.className = "secondary";
    e.textContent = label;
    e.onclick = action;
    return e;
  };
  function navigate(p) {
    path = p;
    clearTimeout(timer);
    load();
  }
  el("usage-up").onclick = () => navigate(parent);
  function schedule(delay) {
    timer = setTimeout(() => {
      if (document.hidden) schedule(60000);
      else load();
    }, delay);
  }
  async function load() {
    let delay = 60000;
    try {
      const r = await fetch(
        "/api/storage-usage/" +
          encodeURIComponent(root.dataset.lab) +
          "?path=" +
          encodeURIComponent(path),
      );
      const d = await r.json();
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
      parent = d.parent;
      el("usage-up").disabled = !path;
      el("usage-time").textContent = new Date(
        d.scanned_at * 1000,
      ).toLocaleString();
      el("usage-capacity").textContent = size(d.capacity);
      el("usage-used").textContent = size(d.used);
      el("usage-free").textContent = size(Math.max(0, d.capacity - d.used));
      const chart = el("usage-allocation");
      chart.replaceChildren();
      chart.append(
        svg("rect", {
          x: 0,
          y: 0,
          width: 1000,
          height: 48,
          fill: "#e9eef2",
          rx: 8,
        }),
      );
      const accounts = el("usage-accounts");
      accounts.replaceChildren();
      let x = 0;
      d.accounts.forEach((a, i) => {
        const width = Math.min(
          1000 - x,
          (a.bytes / Math.max(1, d.used)) * 1000,
        );
        chart.append(
          svg("rect", {
            x,
            y: 0,
            width,
            height: 48,
            fill: colors[i % colors.length],
          }),
        );
        x += width;
        const b = button(
          a.name +
            " · " +
            size(a.bytes) +
            " · " +
            ((a.bytes / Math.max(1, d.used)) * 100).toFixed(1) +
            "%",
          () => navigate(a.path),
        );
        const dot = svg("svg", {
          width: 12,
          height: 12,
          viewBox: "0 0 12 12",
          "aria-hidden": "true",
        });
        dot.append(
          svg("circle", {
            cx: 6,
            cy: 6,
            r: 5,
            fill: colors[i % colors.length],
          }),
        );
        b.prepend(dot);
        b.disabled = !a.bytes;
        accounts.append(b);
      });
      const other = Math.max(
        0,
        d.used - d.accounts.reduce((n, a) => n + a.bytes, 0),
      );
      chart.append(
        svg("rect", {
          x,
          y: 0,
          width: Math.min(1000 - x, (other / Math.max(1, d.used)) * 1000),
          height: 48,
          fill: "#9baab6",
        }),
      );
      const more = document.createElement("span");
      more.textContent =
        t(d.partial ? "미집계·기타" : "기타·관리 영역") + " · " + size(other);
      accounts.append(more);
      el("usage-path").textContent = path || t("전체 경로");
      el("usage-host").textContent = d.root + (path ? "/" + path : "");
      const list = el("usage-paths");
      list.replaceChildren();
      d.entries.forEach((a, i) => {
        const b = button("", () => navigate(a.path));
        b.className = "usage-path-row";
        b.disabled = !a.directory;
        const title = document.createElement("strong");
        title.textContent = (a.directory ? "▰ " : "▤ ") + a.name;
        const amount = document.createElement("span");
        amount.textContent =
          size(a.bytes) +
          " · " +
          ((a.bytes / Math.max(1, d.selected)) * 100).toFixed(1) +
          "%";
        const bar = svg("svg", {
          viewBox: "0 0 500 10",
          preserveAspectRatio: "none",
          "aria-hidden": "true",
        });
        bar.append(
          svg("rect", {
            x: 0,
            y: 0,
            width: 500,
            height: 10,
            fill: "#edf2f5",
            rx: 5,
          }),
          svg("rect", {
            x: 0,
            y: 0,
            width: Math.min(500, (500 * a.bytes) / Math.max(1, d.selected)),
            height: 10,
            fill: colors[i % colors.length],
            rx: 5,
          }),
        );
        b.append(title, amount, bar);
        list.append(b);
      });
      el("usage-state").textContent = d.partial
        ? t("부분 집계 · 일부 항목을 집계하지 못했습니다.")
        : d.refreshing
          ? t("이전 집계 표시 · 갱신 중")
          : t("집계 완료");
      if (!d.entries.length)
        el("usage-state").textContent = t(
          "세부 경로 집계는 최대 4단계까지 제공합니다.",
        );
      if (d.remaining)
        el("usage-state").textContent +=
          " · " + t("나머지 경로") + " " + size(d.remaining);
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
