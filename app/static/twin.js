(() => {
  const root = document.getElementById("twin");
  if (!root) return;

  let data = JSON.parse(root.dataset.state);
  let catalog = JSON.parse(root.dataset.catalog || '{"labs":[],"jobs":[],"storage_limit":100}');
  const csrf = root.dataset.csrf || "";
  const accessHost = root.dataset.accessHost || "";
  const storageMax = Number(root.dataset.storageMax || catalog.storage_limit || 1000);

  let mode = null; // null | "lab" | "create"
  let activeLabId = null;
  let activeTab = "summary"; // summary | accounts | resources | backups
  let createGpu = null;
  let hoveredLabId = null;
  let assigningGpu = null;
  let stagedGpu = null; // { gpu: number, labId: string }
  let dragging = null; // { gpu, x, y, targetLabId }
  let busy = false;
  let timer = null;
  let retry = 5000;

  const t = (value) => (typeof tr === "function" ? tr(String(value)) : String(value));
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = t(text);
    if (cls) n.className = cls;
    return n;
  };
  const rawEl = (tag, rawText, cls) => {
    const n = document.createElement(tag);
    if (rawText !== undefined && rawText !== null) n.textContent = String(rawText);
    if (cls) n.className = cls;
    return n;
  };
  const svgNode = (tag, attrs = {}) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    return n;
  };
  const svgCloseIcon = () => {
    const svg = svgNode("svg", {
      viewBox: "0 0 24 24",
      width: 15,
      height: 15,
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "2",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
    });
    svg.append(
      svgNode("path", { d: "M18 6 6 18" }),
      svgNode("path", { d: "m6 6 12 12" }),
    );
    return svg;
  };
  const vramGb = (usedMib, totalMib) =>
    (Number(usedMib || 0) / 1024).toFixed(1) + " / " + Math.round(Number(totalMib || 0) / 1024) + " GB";

  const indices = (lab) => (lab.gpu_indices && lab.gpu_indices.length ? lab.gpu_indices : [Number(lab.gpu)]).map(Number);
  const owners = (gpuIdx) => data.labs.filter((l) => indices(l).includes(Number(gpuIdx)));
  const catalogLab = (labId) => (catalog.labs || []).find((l) => l.id === labId) || null;
  const accentClass = (labId) => {
    const i = data.labs.findIndex((l) => l.id === labId);
    return "lab-accent-" + (i >= 0 ? i % 6 : 0);
  };
  const capGb = (gb) => {
    const v = Number(gb || 0);
    return v >= 1000 ? (v / 1000).toFixed(1) + " TB" : v.toFixed(0) + " GB";
  };
  const capUsage = (gb) => {
    const v = Number(gb || 0);
    return v >= 1000 ? (v / 1000).toFixed(2) + " TB" : v.toFixed(1) + " GB";
  };
  const maxLabGpuUtil = (lab) => {
    const idxs = indices(lab);
    const utils = data.gpus.filter((g) => idxs.includes(g.index)).map((g) => Number(g.util || 0));
    return utils.length ? Math.max(...utils) : 0;
  };

  function syncUrlState() {
    const url = new URL(location.href);
    url.searchParams.delete("lab");
    url.searchParams.delete("tab");
    url.searchParams.delete("create");
    url.searchParams.delete("gpu");
    if (mode === "lab" && activeLabId) {
      url.searchParams.set("lab", activeLabId);
      if (activeTab && activeTab !== "summary") url.searchParams.set("tab", activeTab);
    } else if (mode === "create") {
      url.searchParams.set("create", "1");
      if (createGpu !== null && createGpu !== undefined) url.searchParams.set("gpu", String(createGpu));
    }
    history.replaceState(null, "", url.pathname + url.search);
    window.orviaSyncLangLinks?.();
  }

  function initFromUrl() {
    const q = new URLSearchParams(location.search);
    const labParam = q.get("lab");
    const tabParam = q.get("tab");
    const createParam = q.get("create");
    const gpuParam = q.get("gpu");
    if (createParam === "1") {
      mode = "create";
      createGpu = gpuParam !== null && /^\d+$/.test(gpuParam) ? Number(gpuParam) : null;
    } else if (labParam && data.labs.some((l) => l.id === labParam)) {
      mode = "lab";
      activeLabId = labParam;
      activeTab = ["summary", "accounts", "resources", "backups"].includes(tabParam) ? tabParam : "summary";
    }
  }

  function openLab(labId, tab = "summary", keepStaged = false) {
    if (!data.labs.some((l) => l.id === labId)) return;
    mode = "lab";
    activeLabId = labId;
    activeTab = tab;
    assigningGpu = null;
    if (!keepStaged && stagedGpu && stagedGpu.labId !== labId) stagedGpu = null;
    syncUrlState();
    renderStage();
    renderPanel();
  }

  function openCreate(gpuIdx = null) {
    if (gpuIdx === null) { window.location.assign("/labs/add"); return; }
    mode = "create";
    activeLabId = null;
    assigningGpu = null;
    stagedGpu = null;
    createGpu = gpuIdx;
    syncUrlState();
    renderStage();
    renderPanel();
  }

  function closePanel() {
    mode = null;
    activeLabId = null;
    hoveredLabId = null;
    assigningGpu = null;
    stagedGpu = null;
    syncUrlState();
    renderStage();
    renderPanel();
  }

  function hiddenInput(name, value) {
    const inp = document.createElement("input");
    inp.type = "hidden";
    inp.name = name;
    inp.value = String(value ?? "");
    return inp;
  }

  function makeSignalBadge(safe, label) {
    return el("span", label, "sig-badge " + (safe ? "sig-safe" : "sig-warn"));
  }

  function stageAssignGpu(gpuIdx, labId) {
    const lab = data.labs.find((l) => l.id === labId);
    if (!lab) return;
    if (!lab.writable) {
      window.orviaToast?.("이 연구실은 현재 변경 보호 대상입니다.");
      return;
    }
    stagedGpu = { gpu: Number(gpuIdx), labId };
    openLab(labId, "resources", true);
  }

  /* ===================== STAGE RENDERING ===================== */
  function renderMetrics() {
    const freeCount = data.gpus.filter((g) => !owners(g.index).length).length;
    const totalUsers = data.labs.reduce((n, l) => n + l.users.length, 0);
    const liveUsers = data.labs.reduce(
      (n, l) => n + l.users.filter((u) => u.status === "running").length,
      0,
    );
    const usedStorage = data.labs.reduce((n, l) => n + Number(l.used_gb || 0), 0);
    const totalStorage = data.labs.reduce((n, l) => n + Number(l.storage_gb || 0), 0);

    document.getElementById("twin-labs").textContent = data.labs.length;
    document.getElementById("twin-users").textContent = totalUsers;
    document.getElementById("twin-users-live").textContent =
      "/ " + liveUsers + " " + t("실행 중");
    document.getElementById("twin-free").textContent = freeCount;
    document.getElementById("twin-storage-text").textContent =
      capGb(usedStorage) + " / " + capGb(totalStorage);
    const memStr = data.memory_used_gib + " / " + data.memory_total_gib + " GiB";
    document.getElementById("twin-memory-text").textContent = memStr;
    document.getElementById("twin-host-ram").textContent = memStr;
    document.getElementById("twin-time").textContent = data.updated;
  }

  function renderStage() {
    root.classList.toggle("is-split", mode !== null);
    const mapEl = document.getElementById("twin-map");
    mapEl?.classList.toggle("is-assign-mode", assigningGpu !== null);
    const resetBtn = document.getElementById("twin-reset");
    if (resetBtn) {
      resetBtn.textContent = mode !== null ? t("패널 접기 · 넓게 보기") : t("전체 연결 보기");
    }
    renderMetrics();

    const pendingBar = document.getElementById("twin-pending-bar");
    const pendingApply = document.getElementById("twin-pending-apply");
    const pendingClear = document.getElementById("twin-pending-clear");
    if (assigningGpu !== null) {
      const lbl = document.getElementById("twin-pending-label");
      lbl.replaceChildren(
        rawEl("strong", "GPU " + assigningGpu),
        document.createTextNode(" · "),
        el("span", "오른쪽 연구실 카드의 연결 버튼을 선택하세요"),
      );
      if (pendingApply) pendingApply.hidden = true;
      if (pendingClear) pendingClear.textContent = t("취소");
      pendingBar.hidden = false;
    } else if (stagedGpu) {
      const target = data.labs.find((l) => l.id === stagedGpu.labId);
      const lbl = document.getElementById("twin-pending-label");
      lbl.replaceChildren(
        rawEl("strong", "GPU " + stagedGpu.gpu),
        document.createTextNode(" -> "),
        rawEl("span", target ? target.title : stagedGpu.labId),
        document.createTextNode(" · "),
        el("span", "배정 대기"),
      );
      if (pendingApply) pendingApply.hidden = false;
      if (pendingClear) pendingClear.textContent = t("초기화");
      pendingBar.hidden = false;
    } else {
      pendingBar.hidden = true;
    }

    const focusLabId = hoveredLabId || (mode === "lab" ? activeLabId : null);

    // Build GPU slots sorted to match lab order (zero crossing wires) + separated free pool
    const gpuContainer = document.getElementById("twin-gpus");
    const gpuFragments = [];
    const effectiveOwnerFor = (gpu) => {
      if (stagedGpu && stagedGpu.gpu === gpu.index) {
        return data.labs.find((l) => l.id === stagedGpu.labId) || owners(gpu.index)[0] || null;
      }
      return owners(gpu.index)[0] || null;
    };
    const assignedGpus = [];
    const freeGpus = [];
    for (const gpu of data.gpus) {
      if (effectiveOwnerFor(gpu)) assignedGpus.push(gpu);
      else freeGpus.push(gpu);
    }
    assignedGpus.sort((a, b) => {
      const oa = effectiveOwnerFor(a);
      const ob = effectiveOwnerFor(b);
      const ia = oa ? data.labs.findIndex((l) => l.id === oa.id) : 9999;
      const ib = ob ? data.labs.findIndex((l) => l.id === ob.id) : 9999;
      return ia !== ib ? ia - ib : a.index - b.index;
    });
    freeGpus.sort((a, b) => a.index - b.index);

    const appendGpuRow = (gpu) => {
      const wrap = document.createElement("div");
      wrap.className = "gpu-slot-wrap";

      const gpuOwners = owners(gpu.index);
      const effectiveOwner = effectiveOwnerFor(gpu);
      const assigned = Boolean(effectiveOwner);
      const isAssigning = assigningGpu === gpu.index;
      const highlighted =
        isAssigning ||
        (focusLabId &&
          (gpuOwners.some((o) => o.id === focusLabId) ||
            (stagedGpu && stagedGpu.gpu === gpu.index && stagedGpu.labId === focusLabId)));

      const row = document.createElement("div");
      row.dataset.gpuRow = String(gpu.index);
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");
      row.className = "gpu-slot-row";
      if (effectiveOwner) row.classList.add(accentClass(effectiveOwner.id));
      if (!assigned) row.classList.add("idle");
      if (isAssigning) row.classList.add("assigning");
      if (Number(gpu.util) > 0) row.classList.add("working");
      if (highlighted) row.classList.add("selected");
      if (focusLabId && !highlighted) row.classList.add("dimmed");
      row.setAttribute(
        "aria-label",
        "GPU " + gpu.index + " · " + (effectiveOwner ? effectiveOwner.title : t("미배정")),
      );

      const left = el("div", null, "gpu-row-left");
      const metaCol = document.createElement("div");
      metaCol.append(
        rawEl("strong", "GPU " + gpu.index),
        rawEl("span", vramGb(gpu.used, gpu.total), "gpu-row-sub"),
      );
      left.append(el("span", null, "gpu-dot"), metaCol);
      row.append(left);

      if (assigned) {
        row.append(rawEl("span", gpu.util + "%", "gpu-util-val"));
      } else {
        const assignBtn = el(
          "button",
          isAssigning ? "대상 선택" : "+ 배정",
          "gpu-assign-btn" + (isAssigning ? " active" : ""),
        );
        assignBtn.type = "button";
        assignBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          assigningGpu = assigningGpu === gpu.index ? null : gpu.index;
          renderStage();
        });
        row.append(assignBtn);
      }

      const pin = document.createElement("span");
      pin.className = "pin-dot pin-dot-right";
      pin.dataset.gpuPin = String(gpu.index);
      pin.title = t("연결 단자를 끌어 연구실에 연결");
      bindPinDrag(pin, gpu.index);
      row.append(pin);

      row.addEventListener("click", () => {
        if (assigned && effectiveOwner) {
          openLab(effectiveOwner.id, "resources");
        } else {
          assigningGpu = assigningGpu === gpu.index ? null : gpu.index;
          renderStage();
        }
      });
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          row.click();
        }
      });
      if (window.OrviaViz?.hint) {
        window.OrviaViz.hint(
          row,
          "GPU " +
            gpu.index +
            " · " +
            gpu.util +
            "%\n" +
            vramGb(gpu.used, gpu.total) +
            " · " +
            gpu.temp +
            " °C",
        );
      }

      wrap.append(row);
      gpuFragments.push(wrap);
    };

    if (assignedGpus.length) {
      gpuFragments.push(el("div", "연구실 연결 슬롯", "gpu-lane-divider"));
      assignedGpus.forEach(appendGpuRow);
    }
    if (freeGpus.length) {
      gpuFragments.push(el("div", "미배정 여유 슬롯", "gpu-lane-divider"));
      freeGpus.forEach(appendGpuRow);
    }
    gpuContainer.replaceChildren(...gpuFragments);

    // Build 1-Column Parallel Lab cards + dashed Create card
    const labContainer = document.getElementById("twin-laboratories");
    const labFragments = [];
    for (const lab of data.labs) {
      const cat = catalogLab(lab.id);
      const isShared = cat?.account_layout === "shared";
      const commonPort = lab.users[0]?.port;
      const card = document.createElement("article");
      const accent = accentClass(lab.id);
      const isSelected = mode === "lab" && activeLabId === lab.id;
      const isDimmed = Boolean(focusLabId && focusLabId !== lab.id);
      card.className =
        "lab-node-25d " +
        accent +
        (isSelected ? " selected" : "") +
        (isDimmed ? " dimmed" : "") +
        (assigningGpu !== null && lab.writable ? " can-assign" : "");
      card.dataset.labNode = lab.id;
      card.setAttribute("tabindex", "0");
      card.setAttribute("role", "button");
      card.setAttribute("aria-pressed", String(isSelected));

      const leftPin = document.createElement("span");
      leftPin.className = "pin-dot pin-dot-left";
      leftPin.dataset.labPin = lab.id;
      card.append(leftPin);

      const top = el("div", null, "lab-node-top");
      const img = document.createElement("img");
      img.className = "lab-model-svg";
      img.src = "/static/models/laboratory.svg";
      img.alt = "";
      img.setAttribute("aria-hidden", "true");

      const meta = el("div", null, "lab-node-meta");
      const titleRow = el("div", null, "lab-node-title-row");
      const titleGrp = el("div", null, "lab-node-title-group");
      titleGrp.append(el("span", null, "gpu-dot"), rawEl("strong", lab.title));

      const util = maxLabGpuUtil(lab);
      const utilBadge = el(
        "span",
        util > 0 ? t("연산 중") + " " + util + "%" : "대기 중",
        "lab-util-badge" + (util > 0 ? " active" : ""),
      );
      if (util > 0) utilBadge.textContent = t("연산 중") + " " + util + "%";
      titleRow.append(titleGrp, utilBadge);

      const idxs = indices(lab);
      const archLabel = isShared
        ? t("공용 컨테이너") + (commonPort ? " · " + t("포트") + " " + commonPort : "")
        : t("개별 컨테이너") + " · " + lab.users.length;
      const archChip = rawEl("span", archLabel, "lab-node-arch" + (isShared ? "" : " is-separate"));
      const sub = rawEl(
        "p",
        "GPU " + idxs.join(", ") + " · " + capGb(lab.storage_gb),
        "lab-node-sub",
      );
      meta.append(titleRow, archChip, sub);
      top.append(img, meta);

      const storageWrap = el("div", null, "lab-storage-wrap");
      const pct = Math.min(
        100,
        Math.max(0, Math.round((Number(lab.used_gb || 0) / Math.max(1, Number(lab.storage_gb || 1))) * 100)),
      );
      const sMeta = el("div", null, "lab-storage-meta");
      sMeta.append(el("span", "연구실 디스크"), rawEl("span", capUsage(lab.used_gb) + " / " + capGb(lab.storage_gb) + " (" + pct + "%)"));
      const barSvg = svgNode("svg", {
        viewBox: "0 0 100 6",
        preserveAspectRatio: "none",
        class: "lab-storage-svg",
        "aria-hidden": "true",
      });
      barSvg.append(
        svgNode("rect", { x: 0, y: 0, width: 100, height: 6, rx: 3, fill: "#e6eef2" }),
        svgNode("rect", { x: 0, y: 0, width: pct, height: 6, rx: 3, class: "lab-storage-fill" }),
      );
      storageWrap.append(sMeta, barSvg);

      const foot = el("div", null, "lab-node-foot");
      const accBtn = rawEl("button", t("계정") + " " + lab.users.length, "lab-quick-btn");
      accBtn.type = "button";
      const resBtn = el("button", "자원 할당", "lab-quick-btn");
      resBtn.type = "button";
      const docBtn = el("button", "안내서", "lab-quick-btn is-right");
      docBtn.type = "button";

      accBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openLab(lab.id, "accounts");
      });
      resBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openLab(lab.id, "resources");
      });
      docBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openLab(lab.id, "backups");
      });
      foot.append(accBtn, resBtn, docBtn);

      card.append(top, storageWrap, foot);
      if (assigningGpu !== null && lab.writable) {
        const assignTargetBtn = rawEl(
          "button",
          "+ GPU " + assigningGpu + " " + t("연결"),
          "inline-assign-btn",
        );
        assignTargetBtn.type = "button";
        const targetGpu = assigningGpu;
        assignTargetBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          stageAssignGpu(targetGpu, lab.id);
        });
        card.append(assignTargetBtn);
      }

      card.addEventListener("pointerenter", () => {
        if (dragging) return;
        hoveredLabId = lab.id;
        updateHighlightClasses();
      });
      card.addEventListener("pointerleave", () => {
        if (dragging) return;
        hoveredLabId = null;
        updateHighlightClasses();
      });
      card.addEventListener("click", () => openLab(lab.id, "summary"));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openLab(lab.id, "summary");
        }
      });

      labFragments.push(card);
    }

    const freeCount = data.gpus.filter((g) => !owners(g.index).length).length;
    const createCard = document.createElement("button");
    createCard.type = "button";
    createCard.className = "lab-create-node";
    createCard.append(
      rawEl("span", "+", "lab-create-plus"),
      assigningGpu !== null
        ? rawEl("strong", "GPU " + assigningGpu + " · " + t("새 연구실 추가"))
        : el("strong", "연구실 추가"),
      rawEl("span", t("미배정 GPU") + " " + freeCount + " " + t("사용 가능")),
    );
    createCard.addEventListener("click", () => openCreate(assigningGpu));
    labFragments.push(createCard);

    labContainer.replaceChildren(...labFragments);
    requestAnimationFrame(drawWires);
  }

  function updateHighlightClasses() {
    const focusLabId = hoveredLabId || (mode === "lab" ? activeLabId : null);
    document.querySelectorAll("[data-lab-node]").forEach((card) => {
      card.classList.toggle("dimmed", Boolean(focusLabId && card.dataset.labNode !== focusLabId));
    });
    document.querySelectorAll("[data-gpu-row]").forEach((row) => {
      const idx = Number(row.dataset.gpuRow);
      const ownerMatch =
        owners(idx).some((o) => o.id === focusLabId) ||
        (stagedGpu && stagedGpu.gpu === idx && stagedGpu.labId === focusLabId);
      row.classList.toggle("dimmed", Boolean(focusLabId && !ownerMatch));
    });
    drawWires();
  }

  function bindPinDrag(pin, gpuIdx) {
    pin.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      assigningGpu = null;
      dragging = { gpu: gpuIdx, x: e.clientX, y: e.clientY, targetLabId: null };
      pin.setPointerCapture(e.pointerId);

      const onMove = (ev) => {
        if (!dragging) return;
        dragging.x = ev.clientX;
        dragging.y = ev.clientY;
        let hit = null;
        document.querySelectorAll("[data-lab-node]").forEach((card) => {
          const r = card.getBoundingClientRect();
          const inside =
            ev.clientX >= r.left - 14 &&
            ev.clientX <= r.right + 12 &&
            ev.clientY >= r.top - 10 &&
            ev.clientY <= r.bottom + 10;
          card.classList.toggle("drop-ready", inside);
          if (inside) hit = card.dataset.labNode;
        });
        dragging.targetLabId = hit;
        drawWires();
      };

      const onUp = () => {
        pin.removeEventListener("pointermove", onMove);
        pin.removeEventListener("pointerup", onUp);
        pin.removeEventListener("pointercancel", onUp);
        const target = dragging?.targetLabId;
        dragging = null;
        document.querySelectorAll("[data-lab-node]").forEach((c) => c.classList.remove("drop-ready"));
        if (target) stageAssignGpu(gpuIdx, target);
        else drawWires();
      };

      pin.addEventListener("pointermove", onMove);
      pin.addEventListener("pointerup", onUp);
      pin.addEventListener("pointercancel", onUp);
    });
  }

  function drawWires() {
    const canvas = document.getElementById("twin-map");
    const svg = document.getElementById("twin-wires");
    if (!canvas || !svg) return;
    const r = canvas.getBoundingClientRect();
    svg.setAttribute("viewBox", "0 0 " + r.width + " " + r.height);
    const focusLabId = hoveredLabId || (mode === "lab" ? activeLabId : null);
    const paths = [];

    for (const lab of data.labs) {
      const pinEl = document.querySelector(`[data-lab-pin="${CSS.escape(lab.id)}"]`);
      const cardEl = document.querySelector(`[data-lab-node="${CSS.escape(lab.id)}"]`);
      const endBox = (pinEl || cardEl)?.getBoundingClientRect();
      if (!endBox) continue;
      const tx = endBox.left + (pinEl ? endBox.width / 2 : 0) - r.left;
      const ty = endBox.top + endBox.height / 2 - r.top;

      const labGpus = new Set(indices(lab));
      if (stagedGpu && stagedGpu.labId === lab.id) labGpus.add(stagedGpu.gpu);

      for (const idx of labGpus) {
        const gPin = document.querySelector(`[data-gpu-pin="${idx}"]`);
        const gRow = document.querySelector(`[data-gpu-row="${idx}"]`);
        const startBox = (gPin || gRow)?.getBoundingClientRect();
        if (!startBox) continue;
        const x = startBox.left + (gPin ? startBox.width / 2 : startBox.width) - r.left;
        const y = startBox.top + startBox.height / 2 - r.top;
        const cp = Math.max(22, Math.abs(tx - x) * 0.48);

        const p = svgNode("path", {
          d: `M ${x} ${y} C ${x + cp} ${y}, ${tx - cp} ${ty}, ${tx} ${ty}`,
        });
        const accent = accentClass(lab.id);
        p.classList.add(accent);
        const isActive = focusLabId === lab.id;
        const isDim = Boolean(focusLabId && focusLabId !== lab.id);
        if (isActive) p.classList.add("active");
        else if (isDim) p.classList.add("dimmed");
        if (stagedGpu && stagedGpu.gpu === idx && stagedGpu.labId === lab.id) {
          p.classList.add("draft-wire");
        }
        const c1 = svgNode("circle", { cx: x, cy: y, r: 3.2, class: "wire-end " + accent + (isActive ? " active" : isDim ? " dimmed" : "") });
        const c2 = svgNode("circle", { cx: tx, cy: ty, r: 3.2, class: "wire-end " + accent + (isActive ? " active" : isDim ? " dimmed" : "") });
        paths.push(p, c1, c2);
      }
    }

    if (dragging) {
      const gPin = document.querySelector(`[data-gpu-pin="${dragging.gpu}"]`);
      const startBox = gPin?.getBoundingClientRect();
      if (startBox) {
        const x = startBox.left + startBox.width / 2 - r.left;
        const y = startBox.top + startBox.height / 2 - r.top;
        const tx = dragging.x - r.left;
        const ty = dragging.y - r.top;
        const cp = Math.max(32, Math.abs(tx - x) * 0.45);
        const draft = svgNode("path", {
          d: `M ${x} ${y} C ${x + cp} ${y}, ${tx - cp} ${ty}, ${tx} ${ty}`,
          class: "draft-wire",
        });
        paths.push(draft);
      }
    }

    svg.replaceChildren(...paths);
  }

  /* ===================== RIGHT SPLIT PANEL ===================== */
  function renderPanel() {
    const panel = document.getElementById("twin-panel");
    if (!panel) return;
    if (mode === null) {
      panel.hidden = true;
      panel.replaceChildren();
      return;
    }
    panel.hidden = false;
    if (mode === "create") {
      panel.replaceChildren(...buildCreatePanel());
      window.orviaBindReview?.(panel);
      return;
    }
    const lab = data.labs.find((l) => l.id === activeLabId);
    if (!lab) {
      closePanel();
      return;
    }
    panel.replaceChildren(...buildLabPanel(lab));
    window.orviaBindReview?.(panel);
  }

  function buildLabPanel(lab) {
    const cat = catalogLab(lab.id);
    const idxs = indices(lab);
    const nextUrl = "/?lab=" + encodeURIComponent(lab.id) + "&tab=" + encodeURIComponent(activeTab);

    // Header
    const head = el("div", null, "split-panel-head");
    const top = el("div", null, "split-head-top");
    const titleBox = el("div", null, "split-head-title");
    const dot = el("span", null, "split-head-dot " + accentClass(lab.id));
    const titleMeta = document.createElement("div");
    titleMeta.append(
      rawEl("h2", lab.title),
      rawEl(
        "p",
        (idxs.length ? "GPU " + idxs.join(", ") : t("미배정")) +
          " · " +
          capUsage(lab.used_gb) +
          " / " +
          capGb(lab.storage_gb),
        "split-head-sub",
      ),
    );
    titleBox.append(dot, titleMeta);

    const actions = el("div", null, "split-head-actions");
    actions.append(
      el("span", lab.writable ? "편집 허용" : "조회 전용", "badge " + (lab.writable ? "running" : "")),
    );
    const fullLink = document.createElement("a");
    fullLink.className = "split-full-link";
    fullLink.href = "/labs/" + encodeURIComponent(lab.id);
    fullLink.textContent = t("전체 보기") + " ›";
    const closeBtn = document.createElement("button");
    closeBtn.className = "split-close-btn";
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", t("닫기"));
    closeBtn.append(svgCloseIcon());
    closeBtn.addEventListener("click", closePanel);
    actions.append(fullLink, closeBtn);
    top.append(titleBox, actions);

    const tabs = el("div", null, "split-tabs");
    const tabDefs = [
      ["summary", t("요약")],
      ["accounts", t("계정") + " (" + lab.users.length + ")"],
      ["resources", t("자원 할당")],
      ["backups", t("백업 · 안내서")],
    ];
    for (const [key, label] of tabDefs) {
      const btn = rawEl("button", label, "split-tab-btn" + (activeTab === key ? " active" : ""));
      btn.type = "button";
      btn.addEventListener("click", () => {
        activeTab = key;
        syncUrlState();
        renderPanel();
      });
      tabs.append(btn);
    }
    head.append(top, tabs);

    // Body
    const body = el("div", null, "split-panel-body");
    if (activeTab === "summary") renderSummaryTab(body, lab, cat, idxs);
    else if (activeTab === "accounts") renderAccountsTab(body, lab, cat, nextUrl);
    else if (activeTab === "resources") renderResourcesTab(body, lab, cat, idxs, nextUrl);
    else renderBackupsTab(body, lab, nextUrl);

    return [head, body];
  }

  function renderSummaryTab(body, lab, cat, idxs) {
    const isoCard = el("div", null, "panel-section-card");
    const isoHead = el("div", null, "panel-card-head");
    isoHead.append(el("strong", "접근 및 저장 격리 구조"));
    isoCard.append(isoHead);

    const stack = el("div", null, "iso-stack");
    const mkIso = (title, pathTag, desc, pill, shared) => {
      const r = el("div", null, "iso-row" + (shared ? " is-shared" : ""));
      const l = document.createElement("div");
      const titleLine = document.createElement("div");
      titleLine.className = "iso-title-line";
      titleLine.append(el("strong", title));
      if (pathTag) titleLine.append(rawEl("code", pathTag, "iso-code"));
      l.append(titleLine, el("span", desc));
      r.append(l, rawEl("span", t(pill), "iso-pill"));
      return r;
    };
    stack.append(
      mkIso(
        "배정 GPU 공동 사용",
        "",
        "할당된 GPU만 컨테이너에 연결",
        idxs.length ? "GPU " + idxs.join(", ") : t("미배정"),
        false,
      ),
      mkIso("개인 홈", "/home/<ID>", "일반 계정은 본인 홈 폴더만 접근", "개인 격리", false),
      mkIso("연구실 저장공간", "", "전체 계정이 하나의 저장공간을 함께 사용", "단일 저장공간", true),
    );
    isoCard.append(stack);
    body.append(isoCard);

    const quotaCard = el("div", null, "panel-section-card soft");
    const qHead = el("div", null, "panel-card-head");
    qHead.append(el("strong", "자원 요약"));
    quotaCard.append(qHead);

    const mkKv = (k, v) => {
      const row = el("div", null, "stat-kv-row");
      row.append(el("span", k), rawEl("strong", v));
      return row;
    };
    const catUsers = cat?.users || [];
    const cpuSet = [...new Set(catUsers.map((u) => u.cpu || 0))];
    const ramSet = [...new Set(catUsers.map((u) => u.ram || 0))];
    let quotaLabel = t("확인 필요");
    if (catUsers.length) {
      if (cpuSet.length === 1 && ramSet.length === 1) {
        const cVal = cpuSet[0] ? cpuSet[0] + " " + t("코어") : t("제한 없음");
        const rVal = ramSet[0] ? ramSet[0] + " GiB" : t("제한 없음");
        quotaLabel = cVal + " · RAM " + rVal;
      } else {
        quotaLabel = t("계정별 한도 설정");
      }
    }
    const runningCnt = lab.users.filter((u) => u.status === "running").length;
    quotaCard.append(
      mkKv("실행 계정", runningCnt + " / " + lab.users.length),
      mkKv(
        "구성 방식",
        t(cat?.account_layout === "shared" ? "공용 컨테이너" : "계정별 컨테이너"),
      ),
      mkKv("CPU · 메모리 한도", quotaLabel),
      mkKv(
        "연구실 디스크",
        capUsage(lab.used_gb) + " / " + capGb(lab.storage_gb),
      ),
    );
    body.append(quotaCard);

    const pathCard = el("div", null, "panel-section-card");
    pathCard.append(
      el("span", "서버 저장 경로 (관리자 SFTP 기준)", "muted"),
      rawEl("code", lab.storage_path || "N/A", "host-storage-path"),
    );
    body.append(pathCard);

    const links = el("div", null, "split-links-row");
    const filesA = document.createElement("a");
    filesA.className = "split-nav-tile";
    filesA.href = "/labs/" + encodeURIComponent(lab.id) + "/files";
    filesA.textContent = t("저장공간 분석") + " ›";
    const maintA = document.createElement("a");
    maintA.className = "split-nav-tile";
    maintA.href = "/containers/" + encodeURIComponent(lab.id);
    maintA.textContent = t("컨테이너 관리") + " ›";
    links.append(filesA, maintA);
    body.append(links);
  }

  function renderAccountsTab(body, lab, cat, nextUrl) {
    const toolbar = el("div", null, "panel-acc-toolbar");
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = t("ID · 이름 · 포트 검색");
    search.autocomplete = "off";
    const toggleAdd = el("button", "+ 계정 추가", "btn-sm");
    toggleAdd.type = "button";
    if (!lab.writable) toggleAdd.disabled = true;
    toolbar.append(search, toggleAdd);
    body.append(toolbar);
    if (cat?.account_backend === "native_etc") {
      body.append(el("p", "비밀번호 변경: 내부 passwd · 관리자 대시보드", "safe-edit"));
    }

    // Collapsible Create Account Form (real /hot-action submit)
    const addBox = el("div", null, "panel-section-card soft");
    addBox.hidden = true;
    const addHead = el("div", null, "panel-card-head");
    addHead.append(el("strong", "새 계정 생성"), makeSignalBadge(true, "무중단 · 즉시 적용"));
    addBox.append(addHead);

    const addForm = document.createElement("form");
    addForm.method = "post";
    addForm.action = "/hot-action";
    addForm.className = "panel-inline-form";
    addForm.dataset.labTitle = lab.title;
    addForm.dataset.impact = t(
      cat?.account_layout === "shared" ? "공용 컨테이너 계정 추가" : "개인 컨테이너 생성",
    );
    addForm.dataset.review = t(
      "개인 계정을 추가하고 연구실 자원을 연결합니다. 기존 사용자의 자료와 실행 환경은 유지됩니다.",
    );
    addForm.dataset.reviewTone = "safe";

    const uniqueContainers = [];
    const seenContainers = new Set();
    for (const u of cat?.users || []) {
      if (seenContainers.has(u.container)) continue;
      seenContainers.add(u.container);
      uniqueContainers.push(u);
    }
    const baseUser = uniqueContainers[0]?.name || lab.users[0]?.name || "";

    addForm.append(
      hiddenInput("csrf", csrf),
      hiddenInput("action", "account_create"),
      hiddenInput("lab", lab.id),
      hiddenInput("confirm", lab.id),
      hiddenInput("next", nextUrl),
    );
    if (cat?.account_layout !== "shared" && uniqueContainers.length > 1) {
      const lbl = el("label", "기준 개발환경");
      const sel = document.createElement("select");
      sel.name = "user";
      for (const u of uniqueContainers) {
        const opt = rawEl("option", u.name + " · " + u.image);
        opt.value = u.name;
        sel.append(opt);
      }
      addForm.append(lbl, sel);
    } else {
      addForm.append(hiddenInput("user", baseUser));
    }

    const row1 = el("div", null, "panel-form-2col");
    const c1 = document.createElement("div");
    const inNewUser = document.createElement("input");
    inNewUser.name = "new_user";
    inNewUser.required = true;
    inNewUser.pattern = "[a-zA-Z][a-zA-Z0-9_-]{1,30}";
    inNewUser.placeholder = "kim";
    c1.append(el("label", "새 계정 ID"), inNewUser);

    const c2 = document.createElement("div");
    const inPw = document.createElement("input");
    inPw.type = "password";
    inPw.name = "password";
    inPw.minLength = 8;
    inPw.maxLength = 128;
    inPw.required = true;
    inPw.autocomplete = "new-password";
    inPw.placeholder = t("8자 이상");
    c2.append(el("label", "새 비밀번호"), inPw);
    row1.append(c1, c2);

    const row2 = el("div", null, "panel-form-2col");
    const c3 = document.createElement("div");
    const inDisp = document.createElement("input");
    inDisp.name = "display_name";
    inDisp.maxLength = 100;
    inDisp.placeholder = t("선택 입력");
    c3.append(el("label", "사용자명"), inDisp);

    const c4 = document.createElement("div");
    const inSid = document.createElement("input");
    inSid.name = "student_id";
    inSid.maxLength = 40;
    inSid.placeholder = t("선택 입력");
    c4.append(el("label", "학번"), inSid);
    row2.append(c3, c4);

    const addBtn = el("button", "계정 생성", "btn-sm");
    addBtn.type = "submit";
    if (!lab.writable) addBtn.disabled = true;

    addForm.append(row1, row2, addBtn);
    addBox.append(addForm);
    body.append(addBox);

    toggleAdd.addEventListener("click", () => {
      addBox.hidden = !addBox.hidden;
    });

    // Account List
    const list = el("div", null, "panel-acc-list");
    const emptyMsg = el("p", "검색 결과 없음", "muted");
    emptyMsg.hidden = lab.users.length > 0;

    const hostAddr = accessHost || location.hostname;
    const itemEls = [];
    for (const u of lab.users) {
      const item = el("div", null, "panel-acc-item");
      const displayName = u.profile?.display_name || u.name;
      item.dataset.search =
        (u.name + " " + displayName + " " + (u.port || "") + " " + (u.profile?.student_id || "")).toLowerCase();

      const sum = el("div", null, "panel-acc-summary");
      const ident = el("div", null, "panel-acc-identity");
      const nameRow = el("div", null, "panel-acc-name-row");
      const dot = el(
        "span",
        null,
        "presence " + (u.status === "running" ? "online" : "offline"),
      );
      nameRow.append(dot, rawEl("strong", u.name));
      const portMeta = rawEl(
        "div",
        t("포트") + " " + (u.port || "—") + " · " + t(u.status === "running" ? "실행 중" : "중지"),
        "panel-acc-port",
      );
      ident.append(nameRow, portMeta);

      const btns = el("div", null, "panel-acc-btns");
      const cmdBtn = el("button", "명령어", "btn-chip");
      cmdBtn.type = "button";
      const sshCmd = "ssh -p " + (u.port || 22) + " " + u.name + "@" + hostAddr;
      cmdBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        window.orviaCopy?.(sshCmd, "SSH 접속 명령어를 복사했습니다.");
      });

      const guideBtn = el("button", "접속 안내 복사", "btn-chip teal");
      guideBtn.type = "button";
      const guideText = [
        "[" + lab.title + "] " + t("GPU 서버 접속 안내"),
        "- " + t("사용자") + ": " + u.name,
        "- " + t("접속 명령") + ": " + sshCmd,
        "- " + t("개인 폴더") + ": /home/" + u.name,
      ].join("\n");
      guideBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        window.orviaCopy?.(guideText, "접속 안내 문구를 복사했습니다.");
      });

      btns.append(cmdBtn, guideBtn);
      sum.append(ident, btns);

      const exp = el("div", null, "panel-acc-expand");
      exp.hidden = true;
      const catUser = cat?.users?.find((cu) => cu.name === u.name);
      const facts = el("div", null, "panel-acc-facts");
      facts.append(
        rawEl("span", t("사용자명") + ": " + (u.profile?.display_name || "N/A")),
        rawEl("span", t("학번") + ": " + (u.profile?.student_id || "N/A")),
        rawEl("span", t("이메일") + ": " + (u.profile?.email || "N/A")),
        rawEl(
          "span",
          "CPU: " +
            (catUser?.cpu ? catUser.cpu + " " + t("코어") : t("제한 없음")) +
            " · RAM: " +
            (catUser?.ram ? catUser.ram + " GiB" : t("제한 없음")),
        ),
      );
      const editLink = document.createElement("a");
      editLink.className = "split-nav-tile";
      editLink.href =
        "/labs/" + encodeURIComponent(lab.id) + "/accounts#account-" + encodeURIComponent(u.name);
      editLink.textContent = t("계정 관리에서 편집 · 비밀번호 변경 · 삭제") + " ›";
      exp.append(facts, editLink);

      sum.addEventListener("click", () => {
        exp.hidden = !exp.hidden;
      });

      item.append(sum, exp);
      list.append(item);
      itemEls.push(item);
    }

    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      for (const node of itemEls) {
        const match = !q || node.dataset.search.includes(q);
        node.hidden = !match;
        if (match) shown++;
      }
      emptyMsg.hidden = shown > 0;
    });

    body.append(list, emptyMsg);
  }

  function renderResourcesTab(body, lab, cat, idxs, nextUrl) {
    // 1. GPU Allocation Card
    const gpuCard = el("div", null, "panel-section-card");
    const gpuHead = el("div", null, "panel-card-head");
    gpuHead.append(el("strong", "GPU 배정"), makeSignalBadge(false, "환경 재생성 · 저장 자료 유지"));
    gpuCard.append(gpuHead);

    const affected = lab.users.map((u) => u.name).join(", ");
    const gpuForm = document.createElement("form");
    gpuForm.method = "post";
    gpuForm.action = "/hot-action";
    gpuForm.className = "panel-inline-form";
    gpuForm.dataset.labTitle = lab.title;
    gpuForm.dataset.impact = t("연구실 환경 재생성");
    if (affected) gpuForm.dataset.affectedAccounts = affected;
    gpuForm.dataset.submitLabel = t("경고 확인 및 적용");
    gpuForm.dataset.review = t(
      "이 연구실의 모든 사용자 접속과 실행 작업이 종료됩니다. 기존 저장공간과 개발환경은 유지됩니다.",
    );

    gpuForm.append(
      hiddenInput("csrf", csrf),
      hiddenInput("action", "gpu_reconfigure"),
      hiddenInput("lab", lab.id),
      hiddenInput("confirm", lab.id),
      hiddenInput("ack_downtime", "yes"),
      hiddenInput("ack_recreate", "yes"),
      hiddenInput("ack_shared", ""),
      hiddenInput("expected_fingerprint", cat?.fingerprint || ""),
      hiddenInput("next", nextUrl),
    );

    const selectedGpus = new Set(idxs);
    if (stagedGpu && stagedGpu.labId === lab.id) selectedGpus.add(stagedGpu.gpu);

    const gpuGrid = el("div", null, "gpu-toggle-grid");
    for (const g of data.gpus) {
      const pill = document.createElement("label");
      pill.className = "gpu-toggle-pill";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.name = "gpu_selection";
      cb.value = String(g.index);
      cb.checked = selectedGpus.has(g.index);

      const other = owners(g.index).filter((o) => o.id !== lab.id);
      const otherTitles = other.map((o) => o.title).join(", ");
      const isBusyOther = !idxs.includes(g.index) && (Number(g.util) > 0 || Number(g.used) > 32);
      if (otherTitles) cb.dataset.ownerTitle = otherTitles;
      cb.dataset.gpuBusy = isBusyOther ? "yes" : "no";

      const subText = other.length
        ? otherTitles
        : Number(g.util) > 0
          ? g.util + "%"
          : t("미배정");

      pill.append(cb, rawEl("span", "GPU " + g.index), rawEl("small", subText));
      gpuGrid.append(pill);
    }

    const gpuSubmit = el("button", "GPU 변경 적용", "btn-sm");
    gpuSubmit.type = "submit";
    if (!lab.writable) gpuSubmit.disabled = true;

    gpuForm.append(
      gpuGrid,
      gpuSubmit,
    );
    gpuCard.append(gpuForm);
    body.append(gpuCard);

    // 2. Lab Disk Expansion Card
    const stCard = el("div", null, "panel-section-card");
    const stHead = el("div", null, "panel-card-head");
    stHead.append(el("strong", "연구실 디스크"), makeSignalBadge(true, "무중단 · 즉시 적용"));
    stCard.append(stHead);

    const curGb = Math.round(Number(lab.allocated_gb || lab.storage_gb || 0));
    stCard.append(
      rawEl(
        "p",
        t("사용량") + ": " + capUsage(lab.used_gb) + " / " + curGb.toLocaleString() + " GB",
        "muted",
      ),
    );

    const stForm = document.createElement("form");
    stForm.method = "post";
    stForm.action = "/action";
    stForm.className = "panel-inline-form";
    stForm.dataset.labTitle = lab.title;
    stForm.dataset.current = curGb + " GB";
    stForm.dataset.impact = t("재시작 없음");
    stForm.dataset.reviewTone = "safe";
    stForm.dataset.review = t("저장공간을 확장합니다. 기존 파일과 실행 환경은 유지됩니다.");

    stForm.append(
      hiddenInput("csrf", csrf),
      hiddenInput("action", "grow"),
      hiddenInput("lab", lab.id),
      hiddenInput("confirm", lab.id),
      hiddenInput("next", nextUrl),
    );

    const sizeInput = document.createElement("input");
    sizeInput.type = "number";
    sizeInput.name = "size_gb";
    sizeInput.min = String(curGb + 1);
    sizeInput.max = String(storageMax);
    sizeInput.value = String(Math.min(storageMax, curGb + 500));
    sizeInput.required = true;

    const presets = el("div", null, "preset-3col");
    for (const delta of [500, 1000, 2000]) {
      const targetGb = curGb + delta;
      const b = rawEl("button", "+" + (delta >= 1000 ? delta / 1000 + " TB" : delta + " GB"), "preset-btn");
      b.type = "button";
      b.disabled = !lab.writable || lab.imported || targetGb > storageMax;
      b.addEventListener("click", () => {
        sizeInput.value = String(targetGb);
        presets.querySelectorAll(".preset-btn").forEach((x) => x.classList.toggle("active", x === b));
      });
      presets.append(b);
    }

    const stBtn = el("button", "저장공간 확장", "btn-sm");
    stBtn.type = "submit";
    stBtn.disabled = !lab.writable || lab.imported || curGb >= storageMax;

    stForm.append(
      presets,
      el("label", "확대 후 용량 (GB)"),
      sizeInput,
      stBtn,
    );
    stCard.append(stForm);
    body.append(stCard);

    // 3. CPU & RAM Limits Card
    const limCard = el("div", null, "panel-section-card soft");
    const limHead = el("div", null, "panel-card-head");
    limHead.append(el("strong", "CPU · 메모리 한도"));

    const scopeWrap = el("div", null, "seg-toggle");
    const btnAll = el("button", "전체 일괄", "active");
    btnAll.type = "button";
    const btnOne = el("button", "개별 계정", "");
    btnOne.type = "button";
    const isSharedLayout = cat?.account_layout === "shared";
    if (!isSharedLayout) {
      scopeWrap.append(btnAll, btnOne);
      limHead.append(scopeWrap);
    }
    limCard.append(limHead);

    const limForm = document.createElement("form");
    limForm.method = "post";
    limForm.action = "/hot-action";
    limForm.className = "panel-inline-form";
    limForm.dataset.labTitle = lab.title;
    limForm.dataset.impact = t("메모리 축소 시 재시작");
    if (affected) limForm.dataset.affectedAccounts = affected;
    limForm.dataset.review = t(
      "메모리 축소 또는 한도 해제 시 실행 작업과 접속이 종료됩니다. 저장 파일은 유지됩니다. 0은 제한 없음을 뜻합니다.",
    );

    const scopeHidden = hiddenInput("scope", isSharedLayout ? "one" : "all");
    const userWrap = document.createElement("div");
    userWrap.hidden = true;

    const catUsers = [];
    const seenU = new Set();
    for (const u of cat?.users || []) {
      if (seenU.has(u.container)) continue;
      seenU.add(u.container);
      catUsers.push(u);
    }

    const userSelect = document.createElement("select");
    userSelect.name = "user";
    if (catUsers.length) {
      for (const u of catUsers) {
        const opt = rawEl("option", isSharedLayout ? t("연구실 전체") : u.name);
        opt.value = u.name;
        opt.dataset.cpu = String(u.cpu || 0);
        opt.dataset.ram = String(Math.round(u.ram || 0));
        userSelect.append(opt);
      }
    } else if (lab.users[0]) {
      const opt = rawEl("option", lab.users[0].name);
      opt.value = lab.users[0].name;
      opt.dataset.cpu = "0";
      opt.dataset.ram = "0";
      userSelect.append(opt);
    }
    userWrap.append(el("label", "대상 계정"), userSelect);

    const allDesc = rawEl(
      "p",
      lab.title + " (" + catUsers.length + ") — " + t("연구실 전체 계정에 동일한 한도를 적용합니다."),
      "muted",
    );

    const limRow = el("div", null, "panel-form-2col");
    const cpuDiv = document.createElement("div");
    const cpuInp = document.createElement("input");
    cpuInp.type = "number";
    cpuInp.name = "cpu";
    cpuInp.min = "0";
    cpuInp.max = String(data.cpu_count || 256);
    cpuInp.step = "0.25";
    cpuInp.value = String(catUsers[0]?.cpu || 0);
    cpuInp.required = true;
    cpuDiv.append(el("label", "CPU (코어, 0=제한 없음)"), cpuInp);

    const ramDiv = document.createElement("div");
    const ramInp = document.createElement("input");
    ramInp.type = "number";
    ramInp.name = "ram";
    ramInp.min = "0";
    ramInp.max = String(data.memory_total_gib || 2048);
    ramInp.value = String(Math.round(catUsers[0]?.ram || 0));
    ramInp.required = true;
    ramDiv.append(el("label", "메모리 (GiB, 0=제한 없음)"), ramInp);
    limRow.append(cpuDiv, ramDiv);

    const limBtn = el("button", "한도 변경 적용", "btn-sm");
    limBtn.type = "submit";
    if (!lab.writable) limBtn.disabled = true;

    const syncLimitTransition = () => {
      const isAll = scopeHidden.value === "all";
      const targetOpts = isAll
        ? [...userSelect.options]
        : userSelect.selectedOptions[0]
          ? [userSelect.selectedOptions[0]]
          : [];
      const newCpu = Number(cpuInp.value);
      const newRam = Number(ramInp.value);
      let anyRelease = false;
      let anyShrink = false;
      for (const opt of targetOpts) {
        const oldCpu = Number(opt.dataset.cpu || 0);
        const oldRam = Number(opt.dataset.ram || 0);
        if ((oldCpu > 0 && newCpu === 0) || (oldRam > 0 && newRam === 0)) {
          anyRelease = true;
        } else if (newRam > 0 && (oldRam === 0 || newRam < oldRam)) {
          anyShrink = true;
        }
      }
      limForm.dataset.limitTransition = anyRelease ? "release" : anyShrink ? "shrink" : "live";
    };

    btnAll.addEventListener("click", () => {
      scopeHidden.value = "all";
      btnAll.classList.add("active");
      btnOne.classList.remove("active");
      userWrap.hidden = true;
      allDesc.hidden = false;
      syncLimitTransition();
    });
    btnOne.addEventListener("click", () => {
      scopeHidden.value = "one";
      btnOne.classList.add("active");
      btnAll.classList.remove("active");
      userWrap.hidden = isSharedLayout;
      allDesc.hidden = true;
      syncLimitTransition();
    });
    userSelect.addEventListener("change", () => {
      const opt = userSelect.selectedOptions[0];
      if (!opt) return;
      cpuInp.value = opt.dataset.cpu || "0";
      ramInp.value = opt.dataset.ram || "0";
      syncLimitTransition();
    });
    cpuInp.addEventListener("input", syncLimitTransition);
    ramInp.addEventListener("input", syncLimitTransition);
    syncLimitTransition();

    limForm.append(
      hiddenInput("csrf", csrf),
      hiddenInput("action", "resources"),
      hiddenInput("lab", lab.id),
      hiddenInput("confirm", lab.id),
      hiddenInput("ack_downtime", ""),
      hiddenInput("next", nextUrl),
      scopeHidden,
      isSharedLayout ? document.createTextNode("") : allDesc,
      userWrap,
      limRow,
      limBtn,
    );
    limCard.append(limForm);
    body.append(limCard);
  }

  function renderBackupsTab(body, lab, nextUrl) {
    // 1. Access Guide PDF Card
    const pdfCard = el("div", null, "panel-section-card");
    const pdfHead = el("div", null, "panel-card-head");
    pdfHead.append(el("strong", "이용 안내서 (PDF)"), makeSignalBadge(true, "무중단"));
    pdfCard.append(
      pdfHead,
      el("p", "연구실 설정을 기준으로 접속 안내서를 생성합니다.", "muted"),
    );

    const pdfGrid = el("div", null, "panel-form-2col");
    for (const [langCode, label] of [
      ["ko", "한국어 PDF"],
      ["en", "English PDF"],
    ]) {
      const f = document.createElement("form");
      f.method = "post";
      f.action = "/manual/pdf";
      f.append(
        hiddenInput("csrf", csrf),
        hiddenInput("lab", lab.id),
        hiddenInput("document_language", langCode),
      );
      const b = rawEl("button", label, langCode === "ko" ? "btn-sm" : "secondary btn-sm");
      b.type = "submit";
      f.append(b);
      pdfGrid.append(f);
    }
    const previewLink = document.createElement("a");
    previewLink.className = "split-nav-tile";
    previewLink.href = "/manual?lab=" + encodeURIComponent(lab.id);
    previewLink.textContent = t("안내서 미리보기 · 추가 안내 입력") + " ›";
    pdfCard.append(pdfGrid, previewLink);
    body.append(pdfCard);

    // 2. Live Backup Form Card
    const bkpCard = el("div", null, "panel-section-card soft");
    const bkpHead = el("div", null, "panel-card-head");
    bkpHead.append(el("strong", "연구실 파일 백업"), makeSignalBadge(true, "재시작 없음"));
    bkpCard.append(
      bkpHead,
      el("p", "컨테이너 파일시스템과 영구 저장공간을 함께 저장합니다. 재시작·일시정지는 수행하지 않습니다.", "muted"),
    );

    if (lab.users.length) {
      const bf = document.createElement("form");
      bf.method = "post";
      bf.action = "/hot-action";
      bf.className = "panel-inline-form";
      bf.dataset.labTitle = lab.title;
      bf.dataset.impact = t("무중단 라이브 백업");
      bf.dataset.submitLabel = t("백업 시작");
      bf.dataset.review = t("컨테이너 파일시스템과 영구 저장공간을 무중단으로 백업합니다.");

      const bSubmit = el("button", "백업 시작", "secondary btn-sm");
      bSubmit.type = "submit";
      if (!lab.writable) bSubmit.disabled = true;

      bf.append(
        hiddenInput("csrf", csrf),
        hiddenInput("action", "backup"),
        hiddenInput("lab", lab.id),
        hiddenInput("confirm", lab.id),
        hiddenInput("consistency", "live"),
        hiddenInput("user", lab.users[0].name),
        hiddenInput("next", nextUrl),
        bSubmit,
      );
      bkpCard.append(bf);
    }

    const recentJobs = (catalog.jobs || []).filter((j) => j.lab === lab.id).slice(0, 3);
    if (recentJobs.length) {
      for (const j of recentJobs) {
        bkpCard.append(rawEl("p", j.time + " · " + t(j.state) + " · " + t(j.message), "muted"));
      }
    }
    body.append(bkpCard);

    // 3. Links to Images & Maintenance
    const links = el("div", null, "split-links-row");
    const imgA = document.createElement("a");
    imgA.className = "split-nav-tile";
    imgA.href = "/containers/" + encodeURIComponent(lab.id) + "/images";
    imgA.textContent = t("환경 템플릿") + " ›";
    const mA = document.createElement("a");
    mA.className = "split-nav-tile";
    mA.href = "/containers/" + encodeURIComponent(lab.id);
    mA.textContent = t("컨테이너 관리") + " ›";
    links.append(imgA, mA);
    body.append(links);
  }

  function buildCreatePanel() {
    const head = el("div", null, "split-panel-head");
    const top = el("div", null, "split-head-top");
    const titleBox = el("div", null, "split-head-title");
    const titleMeta = document.createElement("div");
    titleMeta.append(
      rawEl("span", "NEW LABORATORY", "host-eyebrow"),
      el("h2", "새 환경 만들기"),
    );
    titleBox.append(titleMeta);

    const actions = el("div", null, "split-head-actions");
    const wizardLink = document.createElement("a");
    wizardLink.className = "split-full-link";
    wizardLink.href =
      createGpu !== null ? "/labs/add/new?gpu=" + encodeURIComponent(createGpu) : "/labs/add/new";
    wizardLink.textContent = t("전체 마법사") + " ›";
    const closeBtn = document.createElement("button");
    closeBtn.className = "split-close-btn";
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", t("닫기"));
    closeBtn.append(svgCloseIcon());
    closeBtn.addEventListener("click", closePanel);
    actions.append(wizardLink, closeBtn);
    top.append(titleBox, actions);
    head.append(top);

    const body = el("div", null, "split-panel-body");
    const safeCard = el("div", "무중단 · 기존 연구실 컨테이너에는 영향을 주지 않습니다.", "safe-edit");
    body.append(safeCard);

    const form = document.createElement("form");
    form.method = "post";
    form.action = "/provision/prepare";
    form.className = "panel-inline-form panel-section-card";
    form.dataset.impact = t("새 연구실 생성 준비");
    form.dataset.reviewTone = "safe";
    form.dataset.submitLabel = t("생성 준비");
    form.dataset.review = t("표시된 구성으로 연구실 생성 계획을 준비합니다. 기존 연구실에는 영향을 주지 않습니다.");

    const genId =
      "lab-" +
      Array.from(crypto.getRandomValues(new Uint8Array(4)), (n) =>
        n.toString(16).padStart(2, "0"),
      ).join("");

    form.append(
      hiddenInput("csrf", csrf),
      hiddenInput("image_mode", "official"),
      hiddenInput("ack_shared", ""),
    );

    const titleInp = document.createElement("input");
    titleInp.name = "title";
    titleInp.required = true;
    titleInp.maxLength = 100;
    titleInp.placeholder = t("예: 로보틱스 연구실");

    const idInp = document.createElement("input");
    idInp.name = "id";
    idInp.required = true;
    idInp.pattern = "[a-z][a-z0-9-]{2,23}";
    idInp.value = genId;

    // GPU Selection
    const defaultIdx =
      createGpu !== null
        ? createGpu
        : [...data.gpus]
            .sort((a, b) => b.index - a.index)
            .find((g) => !owners(g.index).length && !g.util && g.used <= 32)?.index ??
          data.gpus[0]?.index ??
          0;

    const gpuGrid = el("div", null, "gpu-toggle-grid");
    for (const g of data.gpus) {
      const pill = document.createElement("label");
      pill.className = "gpu-toggle-pill";
      const rb = document.createElement("input");
      rb.type = "radio";
      rb.name = "gpu_index";
      rb.value = String(g.index);
      rb.required = true;
      rb.checked = g.index === defaultIdx;
      const gOwners = owners(g.index);
      const ownerTitles = gOwners.map((o) => o.title).join(", ");
      if (ownerTitles) rb.dataset.ownerTitle = ownerTitles;
      rb.dataset.gpuBusy = Number(g.util) > 0 || Number(g.used) > 32 ? "yes" : "no";
      pill.append(
        rb,
        rawEl("span", "GPU " + g.index),
        rawEl("small", gOwners.length ? ownerTitles : t("미배정")),
      );
      gpuGrid.append(pill);
    }

    // Storage Selection
    const stInp = document.createElement("input");
    stInp.type = "number";
    stInp.name = "storage_gb";
    stInp.min = "1";
    stInp.max = String(storageMax);
    stInp.value = String(Math.min(1000, storageMax));
    stInp.required = true;

    const stPresets = el("div", null, "preset-3col");
    for (const [gb, lbl] of [
      [500, "500 GB"],
      [1000, "1 TB"],
      [5000, "5 TB"],
    ]) {
      const b = rawEl("button", lbl, "preset-btn" + (Number(stInp.value) === gb ? " active" : ""));
      b.type = "button";
      b.disabled = gb > storageMax;
      b.addEventListener("click", () => {
        stInp.value = String(gb);
        stPresets.querySelectorAll(".preset-btn").forEach((x) => x.classList.toggle("active", x === b));
      });
      stPresets.append(b);
    }

    // Official Image Picker
    const imgRow = el("div", null, "panel-form-2col");
    const pDiv = document.createElement("div");
    const provSel = document.createElement("select");
    provSel.name = "image_provider";
    provSel.append(
      Object.assign(document.createElement("option"), { value: "cuda", textContent: "NVIDIA CUDA" }),
      Object.assign(document.createElement("option"), { value: "pytorch", textContent: "NVIDIA PyTorch" }),
    );
    pDiv.append(el("label", "공급자"), provSel);

    const tDiv = document.createElement("div");
    const tagSel = document.createElement("select");
    tagSel.name = "image_tag";
    tagSel.required = true;
    tDiv.append(el("label", "이미지 버전"), tagSel);
    imgRow.append(pDiv, tDiv);

    const imgStatus = el("p", "공식 목록 조회 중", "muted");
    let tagSeq = 0;
    const loadCreateTags = async () => {
      const seq = ++tagSeq;
      tagSel.replaceChildren();
      tagSel.disabled = true;
      imgStatus.textContent = t("공식 목록 조회 중");
      try {
        const res = await fetch("/api/images/" + provSel.value);
        if (!res.ok) throw Error();
        const payload = await res.json();
        if (seq !== tagSeq) return;
        const tags = (payload.tags || []).filter(
          (x) => provSel.value !== "cuda" || x.tag.toLowerCase().includes("ubuntu"),
        );
        for (const item of tags) {
          const o = document.createElement("option");
          o.value = item.tag;
          o.textContent = item.tag;
          tagSel.append(o);
        }
        tagSel.disabled = !tags.length;
        imgStatus.textContent =
          t(payload.error || (payload.stale ? "캐시된 목록" : "공식 목록")) + " · " + tags.length;
      } catch (_) {
        if (seq !== tagSeq) return;
        imgStatus.textContent = t("공식 목록 조회 실패");
      }
    };
    provSel.addEventListener("change", loadCreateTags);
    loadCreateTags();

    // First Account
    const accRow = el("div", null, "panel-form-2col");
    const uDiv = document.createElement("div");
    const uInp = document.createElement("input");
    uInp.name = "new_user";
    uInp.required = true;
    uInp.pattern = "[a-z][a-z0-9_]{1,30}";
    uInp.placeholder = "researcher1";
    uDiv.append(el("label", "첫 계정 ID"), uInp);

    const pwDiv = document.createElement("div");
    const pwInp = document.createElement("input");
    pwInp.type = "password";
    pwInp.name = "password";
    pwInp.minLength = 8;
    pwInp.maxLength = 128;
    pwInp.required = true;
    pwInp.autocomplete = "new-password";
    pwDiv.append(el("label", "비밀번호"), pwInp);
    accRow.append(uDiv, pwDiv);

    const submitBtn = el("button", "생성 설정 검토", "");
    submitBtn.type = "submit";

    form.append(
      el("label", "연구실 이름"),
      titleInp,
      el("label", "연구실 ID"),
      idInp,
      el("label", "배정 GPU"),
      gpuGrid,
      el("label", "공유 저장공간 (GB)"),
      stPresets,
      stInp,
      imgRow,
      imgStatus,
      accRow,
      submitBtn,
    );
    body.append(form);
    return [head, body];
  }

  /* ===================== SYNC & EVENTS ===================== */
  async function sync() {
    if (document.hidden || busy) return;
    busy = true;
    try {
      const [statusRes, catRes] = await Promise.all([
        fetch("/api/status", { cache: "no-store", signal: AbortSignal.timeout(12000) }),
        fetch("/api/catalog", { cache: "no-store", signal: AbortSignal.timeout(12000) }),
      ]);
      if (!statusRes.ok) {
        throw Error(statusRes.status === 401 ? "세션 만료 · 다시 로그인" : "연결 지연 · 자동 재시도");
      }
      data = await statusRes.json();
      if (catRes.ok) catalog = await catRes.json();
      renderStage();
      retry = 5000;
      document.getElementById("twin-sync").textContent = t("실시간 동기화");
    } catch (e) {
      retry = Math.min(retry * 2, 30000);
      document.getElementById("twin-sync").textContent = t(
        e.message && e.message.startsWith("세션") ? e.message : "연결 지연 · 자동 재시도",
      );
    } finally {
      busy = false;
      clearTimeout(timer);
      if (!document.hidden) timer = setTimeout(sync, retry);
    }
  }

  document.getElementById("twin-open-create")?.addEventListener("click", (e) => {
    e.preventDefault();
    openCreate(null);
  });
  document.getElementById("twin-reset")?.addEventListener("click", closePanel);
  document.getElementById("twin-pending-clear")?.addEventListener("click", () => {
    assigningGpu = null;
    stagedGpu = null;
    renderStage();
    if (mode === "lab" && activeTab === "resources") renderPanel();
  });
  document.getElementById("twin-pending-apply")?.addEventListener("click", () => {
    if (stagedGpu) openLab(stagedGpu.labId, "resources", true);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || document.querySelector("dialog[open]")) return;
    if (assigningGpu !== null) {
      assigningGpu = null;
      renderStage();
    } else if (mode !== null) {
      closePanel();
    }
  });

  new ResizeObserver(() => requestAnimationFrame(drawWires)).observe(
    document.getElementById("twin-map"),
  );
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden) sync();
  });

  initFromUrl();
  renderStage();
  renderPanel();
  (window.orviaTrReady || Promise.resolve()).finally(() => {
    renderStage();
    renderPanel();
    syncUrlState();
    timer = setTimeout(sync, 5000);
  });
})();
