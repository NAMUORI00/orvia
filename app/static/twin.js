(() => {
  const root = document.getElementById("twin");
  if (!root) return;
  let data = JSON.parse(root.dataset.state),
    selected = null,
    busy = false,
    timer,
    retry = 5000;
  const gpuNodes = new Map(),
    labNodes = new Map();
  let dictionary = {};
  const t = (value) =>
    dictionary[value] || (typeof tr === "function" ? tr(value) : value);
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = t(String(text));
    if (cls) n.className = cls;
    return n;
  };
  const indices = (lab) => lab.gpu_indices || [Number(lab.gpu)];
  const owners = (index) =>
    data.labs.filter((l) => indices(l).includes(Number(index)));
  const capacity = (value) =>
    Number(value) >= 1000
      ? (Number(value) / 1000).toFixed(2) + " TB"
      : Number(value).toFixed(1) + " GB";
  const selection = (kind, id) => {
    selected = { kind, id };
    render();
  };
  function card(lab) {
    const button = el("button", undefined, "twin-lab");
    button.type = "button";
    const head = el("div", undefined, "twin-lab-head");
    head.append(el("span", "▦", "room-symbol"), el("strong", lab.title));
    button.append(head, el("small", ""), el("div", undefined, "mini-users"));
    button.addEventListener("click", () => selection("lab", lab.id));
    return button;
  }
  function render() {
    const ids = new Set(data.labs.map((l) => l.id));
    for (const [id, n] of labNodes)
      if (!ids.has(id)) {
        n.remove();
        labNodes.delete(id);
      }
    const gpuIds = new Set(data.gpus.map((g) => g.index));
    for (const [id, n] of gpuNodes)
      if (!gpuIds.has(id)) {
        n.remove();
        gpuNodes.delete(id);
      }
    const activeLab =
      selected?.kind === "lab"
        ? data.labs.find((l) => l.id === selected.id)
        : null;
    for (const gpu of [...data.gpus].sort((a, b) => b.index - a.index)) {
      let n = gpuNodes.get(gpu.index);
      if (!n) {
        n = el("button", undefined, "twin-gpu");
        n.type = "button";
        n.append(
          el("i", undefined, "gpu-led"),
          el("span", "GPU " + gpu.index),
          el("small", ""),
        );
        n.addEventListener("click", () => {
          const labs = owners(gpu.index);
          selection(
            labs.length === 1 ? "lab" : "gpu",
            labs.length === 1 ? labs[0].id : gpu.index,
          );
        });
        document.getElementById("twin-gpus").append(n);
        gpuNodes.set(gpu.index, n);
      }
      const assigned = owners(gpu.index).length > 0,
        active =
          (activeLab && indices(activeLab).includes(gpu.index)) ||
          (selected?.kind === "gpu" && selected.id === gpu.index);
      n.classList.toggle("assigned", assigned);
      n.classList.toggle("selected", !!active);
      n.setAttribute("aria-pressed", String(!!active));
      n.querySelector("small").textContent = assigned
        ? gpu.util + "%"
        : t(gpu.util > 0 || gpu.used > 32 ? "사용 확인" : "미배정");
      n.setAttribute(
        "aria-label",
        "GPU " +
          gpu.index +
          " · " +
          (assigned
            ? owners(gpu.index)
                .map((l) => l.title)
                .join(", ")
            : t("미배정")),
      );
    }
    for (const lab of data.labs) {
      let n = labNodes.get(lab.id);
      if (!n) {
        n = card(lab);
        labNodes.set(lab.id, n);
        document.getElementById("twin-laboratories").append(n);
      }
      n.querySelector("strong").textContent = lab.title;
      n.querySelector("small").textContent =
        "GPU " +
        indices(lab).join(", ") +
        " · " +
        capacity(lab.storage_gb) +
        " · " +
        t("사용자") +
        " " +
        lab.users.length;
      n.classList.toggle("selected", activeLab?.id === lab.id);
      n.setAttribute("aria-pressed", String(activeLab?.id === lab.id));
      n.querySelector(".mini-users").replaceChildren(
        ...lab.users.map((u) => {
          const dot = el("i", undefined, u.status === "running" ? "live" : "");
          dot.title = u.name;
          return dot;
        }),
      );
    }
    document.getElementById("twin-labs").textContent = data.labs.length;
    document.getElementById("twin-users").textContent = data.labs.reduce(
      (n, l) => n + l.users.length,
      0,
    );
    document.getElementById("twin-free").textContent = data.gpus.filter(
      (g) => !owners(g.index).length,
    ).length;
    document.getElementById("twin-memory").textContent =
      data.memory_used_gib + " / " + data.memory_total_gib + " GiB";
    document.getElementById("twin-time").textContent = data.updated;
    details(activeLab);
    requestAnimationFrame(wires);
  }
  function details(lab) {
    if (!selected) return;
    const box = document.getElementById("twin-detail");
    const oldFocus = document.activeElement?.dataset?.detailAction;
    const nodes = [];
    const row = (label, value) => {
      const n = el("div", undefined, "detail-stat");
      n.append(el("span", label), el("strong", value));
      nodes.push(n);
    };
    const link = (label, path) => {
      const a = el("a", label);
      a.href = path;
      a.dataset.detailAction = label;
      a.append(el("span", "›"));
      return a;
    };
    if (lab) {
      nodes.push(
        el("span", lab.writable ? "편집 허용" : "조회 전용", "status-tag"),
        el("h2", lab.title),
      );
      row(
        "배정 GPU",
        indices(lab)
          .map((i) => "GPU " + i)
          .join(", "),
      );
      row("공유 저장공간", capacity(lab.storage_gb));
      row("사용량", capacity(lab.used_gb));
      const bar = el("progress");
      bar.max = lab.storage_gb || 1;
      bar.value = lab.used_gb;
      bar.setAttribute("aria-label", t("저장공간 사용량"));
      nodes.push(bar);
      nodes.push(el("h3", "사용자"));
      const users = el("div", undefined, "detail-users");
      users.append(
        ...lab.users.map((u) =>
          el("span", (u.status === "running" ? "● " : "○ ") + u.name),
        ),
      );
      nodes.push(users);
      const actions = el("div", undefined, "twin-actions"),
        url = "/labs/" + encodeURIComponent(lab.id);
      actions.append(
        link("연구실 관리", url),
        link("사용자 관리", url + "/accounts"),
        link("자원 배정", url + "/resources"),
        link("이용 안내서", "/manual?lab=" + encodeURIComponent(lab.id)),
      );
      nodes.push(actions);
    } else if (selected.kind === "gpu") {
      const gpu = data.gpus.find((g) => g.index === selected.id);
      if (!gpu) {
        selected = null;
        box.replaceChildren(el("p", "선택 대상 없음"));
        return;
      }
      nodes.push(
        el("span", owners(gpu.index).length ? "배정" : "미배정", "status-tag"),
        el("h2", "GPU " + gpu.index),
      );
      row("기종", gpu.name);
      row("GPU 메모리", (gpu.total / 1024).toFixed(1) + " GiB");
      row("사용률", gpu.util + "%");
      nodes.push(
        el("p", "자원 배정 전 실행 작업과 연구실 배정 상태를 확인합니다."),
      );
      const actions = el("div", undefined, "twin-actions");
      for (const owner of owners(gpu.index))
        actions.append(
          link(owner.title, "/labs/" + encodeURIComponent(owner.id)),
        );
      actions.append(link("연구실 생성", "/provision"));
      nodes.push(actions);
    } else {
      selected = null;
      nodes.push(el("p", "선택 대상 없음"));
    }
    box.replaceChildren(...nodes);
    if (oldFocus) {
      const target = [...box.querySelectorAll("[data-detail-action]")].find(
        (n) => n.dataset.detailAction === oldFocus,
      );
      target?.focus({ preventScroll: true });
    }
  }
  function wires() {
    const canvas = document.getElementById("twin-map"),
      svg = document.getElementById("twin-wires"),
      r = canvas.getBoundingClientRect();
    svg.setAttribute("viewBox", `0 0 ${r.width} ${r.height}`);
    const paths = [];
    for (const lab of data.labs) {
      const end = labNodes.get(lab.id)?.getBoundingClientRect();
      if (!end) continue;
      for (const index of indices(lab)) {
        const start = gpuNodes.get(index)?.getBoundingClientRect();
        if (!start) continue;
        const x = start.right - r.left,
          y = start.top + start.height / 2 - r.top,
          tx = end.left - r.left,
          ty = end.top + end.height / 2 - r.top;
        const p = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "path",
        );
        p.setAttribute(
          "d",
          `M ${x} ${y} C ${x + 30} ${y}, ${tx - 30} ${ty}, ${tx} ${ty}`,
        );
        if (selected?.kind === "lab" && selected.id === lab.id)
          p.classList.add("active");
        paths.push(p);
      }
    }
    svg.replaceChildren(...paths);
  }
  async function sync() {
    if (document.hidden || busy) return;
    busy = true;
    try {
      const response = await fetch("/api/status", {
        cache: "no-store",
        signal: AbortSignal.timeout(12000),
      });
      if (!response.ok)
        throw Error(
          response.status === 401
            ? "세션 만료 · 다시 로그인"
            : "연결 지연 · 자동 재시도",
        );
      data = await response.json();
      render();
      retry = 5000;
      document.getElementById("twin-sync").textContent = t("실시간 동기화");
    } catch (e) {
      retry = Math.min(retry * 2, 30000);
      document.getElementById("twin-sync").textContent = t(
        e.message.startsWith("세션") ? e.message : "연결 지연 · 자동 재시도",
      );
    } finally {
      busy = false;
      clearTimeout(timer);
      if (!document.hidden) timer = setTimeout(sync, retry);
    }
  }
  new ResizeObserver(wires).observe(document.getElementById("twin-map"));
  document
    .getElementById("twin-laboratories")
    .addEventListener("scroll", wires);
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden) sync();
  });
  fetch("/api/translations")
    .then((r) => (r.ok ? r.json() : {}))
    .then((d) => {
      dictionary = d;
    })
    .catch(() => {})
    .finally(() => {
      render();
      timer = setTimeout(sync, 5000);
    });
})();
