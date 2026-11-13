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
      : n >= 1e9
        ? (n / 1e9).toFixed(1) + " GB"
        : n >= 1e6
          ? (n / 1e6).toFixed(1) + " MB"
          : (n / 1024).toFixed(1) + " KiB";
  const colors = ["#218878", "#5b88bd", "#9872b4", "#cb984d"];
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
  function render() {
    if (!data?.latest) return;
    const d = data.latest,
      h = data.history,
      stale = Date.now() / 1000 - d.ts > 180;
    el("monitor-time").textContent = new Date(d.ts * 1000).toLocaleString();
    el("monitor-error").textContent = stale
      ? t("수집 지연 · 마지막 기록 표시")
      : "";
    const warning = issues();
    el("monitor-health").textContent = t(
      stale ? "수집 지연" : warning.length ? "확인 필요" : "모든 환경 실행 중",
    );
    el("monitor-health").classList.toggle(
      "attention",
      stale || !!warning.length,
    );
    const panels = [
      {
        name: "서버 CPU 사용률",
        key: "cpu",
        color: colors[0],
        max: 100,
        format: (v) => v.toFixed(1) + "%",
        values: h.map((p) => ({ ts: p.ts, value: p.cpu_util })),
      },
      {
        name: "평균 GPU 사용률",
        key: "gpu",
        color: colors[1],
        max: 100,
        format: (v) => v.toFixed(1) + "%",
        values: h.map((p) => ({ ts: p.ts, value: p.gpu })),
      },
      {
        name: "시스템 메모리",
        key: "memory",
        color: colors[2],
        max: d.memory_total / 1073741824,
        format: (v) => v.toFixed(1) + " GiB",
        values: h.map((p) => ({ ts: p.ts, value: p.memory / 1073741824 })),
      },
      {
        name: "네트워크",
        key: "network",
        color: colors[3],
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
      const card = node("section", "", "metric-card");
      const button = node("button", t(p.name), "metric-title");
      button.type = "button";
      button.onclick = () => open(p.key === "network" ? "network" : "hardware");
      card.append(button);
      series(card, t(p.name), p.values, p.format, p.color, p.max);
      const foot = node("span", t("사용 추이"), "metric-caption");
      card.append(foot);
      overview.append(card);
    });
    const users = el("monitor-users");
    users.replaceChildren();
    d.accounts.forEach((a) => {
      const card = node("article", "", "account-tile");
      const button = node("button", "", "account-select");
      button.type = "button";
      const status = node(
        "span",
        "",
        "presence " + (a.running ? "online" : "offline"),
      );
      status.setAttribute("aria-label", t(a.running ? "실행 중" : "정지"));
      button.append(
        status,
        node("strong", a.user),
        node("span", "›", "account-arrow"),
      );
      button.onclick = () => open("account", a.user);
      card.append(button);
      const p = h.map((row) => ({
        ts: row.ts,
        value:
          row.accounts.find((u) => u.user === a.user)?.cpu == null
            ? null
            : row.accounts.find((u) => u.user === a.user).cpu / 100,
      }));
      series(
        card,
        a.user + " · CPU",
        p,
        (v) => v.toFixed(2) + " " + t("코어"),
        a.running ? colors[0] : "#9cabb3",
      );
      card.append(
        node("span", t(a.running ? "실행 중" : "정지"), "metric-caption"),
      );
      users.append(card);
    });
    renderNetwork(el("network-ranking"));
    if (el("monitor-detail").open) renderDetail();
  }
  function renderNetwork(target) {
    target.replaceChildren();
    const usage = data.network_usage || [];
    const max = Math.max(1, ...usage.map((a) => a.rx + a.tx));
    usage.forEach((a) => {
      const button = node("button", "", "network-account");
      button.type = "button";
      button.append(node("strong", a.user));
      const bar = node("span", "", "network-bar");
      ["rx", "tx"].forEach((k) => {
        const segment = node("span", "", "network-" + k);
        segment.style.width = (100 * a[k]) / max + "%";
        bar.append(segment);
      });
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
      const a = d.accounts.find((a) => a.user === selected);
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
      const link = node("a", t("저장공간 분석"), "button");
      link.href = "/labs/" + encodeURIComponent(a.lab) + "/files";
      body.append(link);
      const net = node("button", t("네트워크 상세"), "secondary");
      net.onclick = () => open("network-account", a.lab + "/" + a.user);
      body.append(net);
      body.append(node("h3", t("CPU 사용 추이")));
      series(
        body,
        "CPU",
        data.history.map((p) => ({
          ts: p.ts,
          value:
            p.accounts.find((u) => u.user === selected)?.cpu == null
              ? null
              : p.accounts.find((u) => u.user === selected).cpu / 100,
        })),
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
        node("p", t("1분 간격 · 7일 보관 · 실행 상태와 자원 지표만 수집")),
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
  el("monitor-detail").addEventListener("close", V.hide);
  el("monitor-hardware-open").onclick = () => open("hardware");
  el("monitor-events-open").onclick = () => open("events");
  el("monitor-info-open").onclick = () => open("info");
  el("monitor-health").onclick = () => data?.latest && open("health");
  function schedule() {
    timer = setTimeout(() => (document.hidden ? schedule() : load()), 60000);
  }
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
  el("monitor-window").onchange = () => {
    clearTimeout(timer);
    load();
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      load();
    }
  });
  load();
})();
