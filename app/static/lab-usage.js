(() => {
  const root = document.querySelector("[data-usage-lab]");
  if (!root) return;
  const t = (s) => (typeof tr === "function" ? tr(s) : s);
  let timer,
    loading = false;
  function bytes(value) {
    const m = /^\s*([\d.]+)\s*(KiB|MiB|GiB|TiB|kB|MB|GB|TB|B)/.exec(
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
            kB: 1e3,
            MB: 1e6,
            GB: 1e9,
            TB: 1e12,
          }[m[2]]
      : null;
  }
  function statusForPct(p) {
    if (p == null) return { cls: "sig-idle", arc: "is-teal", label: "수집 대기" };
    if (p >= 85) return { cls: "sig-crit", arc: "is-crit", label: "혼잡" };
    if (p >= 65) return { cls: "sig-warn", arc: "is-amber", label: "주의" };
    if (p >= 25) return { cls: "sig-info", arc: "is-sky", label: "활발" };
    if (p >= 5) return { cls: "sig-safe", arc: "is-teal", label: "쾌적" };
    return { cls: "sig-safe", arc: "is-teal", label: "여유" };
  }
  function metric(node, key, value, total, detail) {
    const p = value != null && total > 0 ? (100 * value) / total : null;
    const isRoot = node === root;
    const valEl = node.querySelector(
      "[data-usage-" + (isRoot ? "total" : "value") + '="' + key + '"]',
    );
    if (valEl) {
      valEl.textContent = p == null ? "N/A" : isRoot ? p.toFixed(1) + "%" : detail;
    }
    const bar = node.querySelector('[data-usage-fill="' + key + '"]');
    if (bar) {
      bar.value = p == null ? 0 : Math.min(100, Math.max(0, p));
      bar.title = p == null ? "N/A" : p.toFixed(2) + "% · " + detail;
    }
    const arc = node.querySelector('[data-usage-arc="' + key + '"]');
    if (arc) {
      const clamped = p == null ? 0 : Math.min(100, Math.max(0, p));
      const vis = clamped === 0 ? 0 : Math.max(2.2, clamped);
      arc.setAttribute("stroke-dasharray", vis.toFixed(1) + " 100");
      const st = statusForPct(p);
      arc.setAttribute("class", "gauge-arc " + (key === "memory" && clamped < 65 ? "is-sky" : st.arc));
      const badge = node.querySelector('[data-usage-badge="' + key + '"]');
      if (badge) {
        badge.className = "sig-badge " + st.cls;
        badge.textContent = t(st.label);
      }
    }
    const rectBar = node.querySelector('[data-usage-bar-rect="' + key + '"]');
    if (rectBar) {
      const w = p == null ? 0 : Math.min(100, Math.max(0, p));
      rectBar.setAttribute("width", w.toFixed(1));
    }
    const extra = node.querySelector(
      "[" +
        (isRoot ? "data-total-detail" : "data-usage-detail") +
        '="' +
        key +
        '"]',
    );
    if (extra) extra.textContent = p == null ? "N/A" : detail;
  }
  function render(data) {
    const stale = !data.ts || Date.now() / 1000 - data.ts > 180;
    root.classList.toggle("stale", stale);
    const timeEl = root.querySelector("[data-usage-time]");
    if (timeEl) {
      const loc = document.documentElement.lang === "en" ? "en-US" : "ko-KR";
      timeEl.textContent = data.ts
        ? new Date(data.ts * 1000).toLocaleTimeString(loc) +
          " · " +
          t(stale ? "수집 지연" : "최근 수집")
        : t("수집 대기");
    }
    let cpu = 0,
      memory = 0,
      known = true;
    root.querySelectorAll("[data-usage-user]").forEach((card) => {
      const a = data.accounts.find((x) => x.user === card.dataset.usageUser);
      const c =
        !a || stale ? null : !a.running ? 0 : a.cpu == null ? null : a.cpu / 100;
      const m = !a || stale ? null : !a.running ? 0 : bytes(a.memory);
      if (c == null || m == null) known = false;
      else {
        cpu += c;
        memory += m;
      }
      const stateEl = card.querySelector("[data-usage-state]");
      if (stateEl) {
        stateEl.textContent = t(
          stale
            ? "수집 지연"
            : !a
              ? "수집 대기"
              : a.running
                ? "실행 중"
                : "중지",
        );
      }
      const compact = !card.classList.contains("usage-user");
      metric(
        card,
        "cpu",
        c,
        data.cpu_count,
        c == null ? "N/A" : compact ? c.toFixed(2) + "c" : c.toFixed(2) + " / " + data.cpu_count + " " + t("코어"),
      );
      metric(
        card,
        "memory",
        m,
        data.memory_total,
        m == null
          ? "N/A"
          : compact
            ? (m / 1024 ** 3).toFixed(1) + "G"
            : (m / 1024 ** 3).toFixed(2) + " / " + (data.memory_total / 1024 ** 3).toFixed(1) + " GiB",
      );
    });
    if (data.shared) {
      cpu = data.shared.cpu == null ? 0 : data.shared.cpu / 100;
      memory = bytes(data.shared.memory) || 0;
      known =
        !stale &&
        data.shared.cpu != null &&
        bytes(data.shared.memory) != null;
    }
    metric(
      root,
      "cpu",
      known ? cpu : null,
      data.cpu_count,
      known && data.cpu_count
        ? cpu.toFixed(2) + " / " + data.cpu_count + " " + t("코어")
        : cpu.toFixed(2) + " " + t("코어"),
    );
    metric(
      root,
      "memory",
      known ? memory : null,
      data.memory_total,
      known && data.memory_total
        ? (memory / 1024 ** 3).toFixed(2) + " / " + (data.memory_total / 1024 ** 3).toFixed(0) + " GiB"
        : (memory / 1024 ** 3).toFixed(2) + " GiB",
    );
    const hostFreeCpu = document.querySelector("[data-host-free-cpu]");
    if (hostFreeCpu) {
      const rem = !stale && data.cpu_util != null && data.cpu_count > 0
        ? Math.max(0, data.cpu_count * (1 - data.cpu_util / 100))
        : null;
      hostFreeCpu.textContent = rem == null ? "N/A" : "(" + t("여유") + " " + rem.toFixed(1) + "c)";
    }
  }
  async function refresh() {
    clearTimeout(timer);
    if (document.hidden || loading) return;
    loading = true;
    try {
      const r = await fetch(
        "/api/lab-usage/" + encodeURIComponent(root.dataset.usageLab),
      );
      if (!r.ok) throw Error();
      render(await r.json());
    } catch (_) {
      render({ ts: null, accounts: [] });
      const timeEl = root.querySelector("[data-usage-time]");
      if (timeEl) timeEl.textContent = t("수집 지연");
    } finally {
      loading = false;
      timer = setTimeout(refresh, 60000);
    }
  }
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden) refresh();
  });
  refresh();
})();
