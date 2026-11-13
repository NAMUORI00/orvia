let messages = {},
  translationPattern = null;
const tr = (text) =>
  typeof text === "string" && translationPattern
    ? text.replace(translationPattern, (m) => messages[m])
    : text;
fetch("/api/translations")
  .then((r) => (r.ok ? r.json() : {}))
  .then((d) => {
    messages = d;
    const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (!Object.keys(d).length) return;
    translationPattern = new RegExp(
      Object.keys(d)
        .sort((a, b) => b.length - a.length)
        .map(escape)
        .join("|"),
      "g",
    );
  })
  .catch(() => {});
document
  .querySelector("[data-refresh]")
  ?.addEventListener("click", () => location.reload());
const form = document.querySelector("#manage-form");
let editing = false;
if (form) {
  const lab = form.querySelector("#lab"),
    action = form.querySelector("#action"),
    user = form.querySelector("#user");
  const sync = () => {
    document.querySelector("#lab-id").textContent = lab.value;
    document.querySelector("#confirm").placeholder = lab.value;
    for (const opt of user.options) {
      opt.hidden = !!opt.dataset.lab && opt.dataset.lab !== lab.value;
    }
    if (user.selectedOptions[0]?.hidden) user.value = "";
    document.querySelector("#password-fields").hidden =
      action.value !== "password";
    document.querySelector("#storage-fields").hidden = action.value !== "grow";
  };
  lab.addEventListener("change", sync);
  action.addEventListener("change", sync);
  form.addEventListener("input", () => (editing = true));
  sync();
  form.addEventListener("submit", (e) => {
    if (
      !confirm(
        "선택한 연구실과 계정에 이 작업을 실행하시겠습니까? 중지·재생성은 실행 중인 작업을 종료합니다.",
      )
    )
      e.preventDefault();
  });
}
const selectLab = (id, scroll = false) => {
  document
    .querySelectorAll("[data-select-lab]")
    .forEach((n) =>
      n.setAttribute("aria-pressed", String(n.dataset.selectLab === id)),
    );
  document
    .querySelectorAll("[data-lab-detail]")
    .forEach((n) => (n.hidden = !!id && n.dataset.labDetail !== id));
  sessionStorage.setItem("h200-selected-lab", id || "");
  if (scroll)
    document.querySelector("#labs")?.scrollIntoView({ block: "start" });
};

document
  .querySelector("#show-all-labs")
  ?.addEventListener("click", () => selectLab(""));
document.querySelectorAll("[data-manage-lab]").forEach((n) =>
  n.addEventListener("click", () => {
    const s = document.querySelector("#lab");
    s.value = n.dataset.manageLab;
    s.dispatchEvent(new Event("change"));
    document.querySelector("#confirm").value = "";
    editing = true;
    document.querySelector("#manage").scrollIntoView({ block: "start" });
  }),
);
const rememberedLab = sessionStorage.getItem("h200-selected-lab");
if (
  rememberedLab &&
  Array.from(document.querySelectorAll("[data-select-lab]")).some(
    (n) => n.dataset.selectLab === rememberedLab,
  )
)
  selectLab(rememberedLab);

if (document.querySelector(".resource-map")) {
  let liveTimer,
    liveBusy = false,
    retry = 5000;
  const setText = (root, selector, value) => {
    const el = root.querySelector(selector);
    if (el) el.textContent = tr(value);
  };
  async function syncLive() {
    if (document.hidden || liveBusy) return;
    liveBusy = true;
    try {
      const response = await fetch("/api/status", {
        cache: "no-store",
        signal: AbortSignal.timeout(12000),
      });
      if (response.status === 401) {
        setText(document, "#sync-status", "세션 만료 · 다시 로그인");
        return;
      }
      if (!response.ok) throw Error("unavailable");
      const d = await response.json();
      retry = 5000;
      setText(document, "#memory-used", d.memory_used_gib);
      setText(document, "#updated-time", d.updated);
      setText(
        document,
        ".server-node p",
        `시스템 메모리 ${d.memory_used_gib} / ${d.memory_total_gib} GiB · 전체 이용자 공유`,
      );
      for (const gpu of d.gpus) {
        const card = Array.from(document.querySelectorAll("[data-gpu]")).find(
          (n) => n.dataset.gpu === String(gpu.index),
        );
        if (!card) continue;
        setText(card, ".badge", gpu.util + "%");
        card.querySelector(".badge").classList.toggle("running", gpu.util > 0);
        card.querySelector("progress").value = gpu.util;
        setText(card, "p", `${gpu.used} / ${gpu.total} MiB`);
        setText(card, "small", gpu.temp + " °C");
      }
      for (const lab of d.labs) {
        const node = Array.from(
          document.querySelectorAll("[data-select-lab]"),
        ).find((n) => n.dataset.selectLab === lab.id);
        const detail = document.getElementById("lab-" + lab.id);
        const gpu = d.gpus.find((g) => String(g.index) === String(lab.gpu));
        if (node) {
          if (gpu) {
            setText(
              node,
              ".node-gpu small",
              `연산 ${gpu.util}% · 메모리 ${gpu.used} / ${gpu.total} MiB`,
            );
            const bar = node.querySelector(".node-gpu progress");
            if (bar) bar.value = gpu.util;
          }
          setText(
            node,
            ".node-storage small",
            `${lab.used_gb} / ${lab.storage_gb} GB 사용`,
          );
          const bar = node.querySelector(".node-storage progress");
          bar.max = lab.storage_gb || 1;
          bar.value = lab.used_gb;
          const users = node.querySelector(".node-users");
          users.replaceChildren(
            ...lab.users.map((u) => {
              const s = document.createElement("span"),
                dot = document.createElement("i");
              dot.className =
                "user-dot" + (u.status === "running" ? " is-running" : "");
              s.append(dot, document.createTextNode(u.name));
              return s;
            }),
          );
        }
        if (detail) {
          setText(
            detail,
            ".card-heading small",
            `GPU ${lab.gpu} · 저장공간 ${lab.used_gb} / ${lab.storage_gb} GB`,
          );
          for (const u of lab.users) {
            const row = Array.from(
              detail.querySelectorAll("[data-account]"),
            ).find((n) => n.dataset.account === u.name);
            if (row) {
              setText(
                row,
                ".badge",
                u.status === "未作成" ? "미생성" : u.status,
              );
              row
                .querySelector(".badge")
                .classList.toggle("running", u.status === "running");
              row.cells[3].textContent = u.started
                ? u.started.slice(0, 19).replace("T", " ") + " UTC"
                : "";
            }
          }
        }
      }
      const tbody = document.querySelector("#activity tbody");
      if (tbody && d.events.length)
        tbody.replaceChildren(
          ...d.events.map((e) => {
            const r = document.createElement("tr");
            for (const v of [
              e.time,
              e.lab,
              e.user || "전체",
              e.action,
              e.result,
            ]) {
              const c = document.createElement("td");
              c.textContent = v;
              r.append(c);
            }
            return r;
          }),
        );
      setText(document, "#sync-status", "동기화 정상 · 5초 간격");
    } catch (e) {
      retry = Math.min(retry * 2, 30000);
      setText(document, "#sync-status", "연결 지연 · 자동 재시도");
    } finally {
      liveBusy = false;
      clearTimeout(liveTimer);
      if (!document.hidden) liveTimer = setTimeout(syncLive, retry);
    }
  }
  document.addEventListener("visibilitychange", () => {
    clearTimeout(liveTimer);
    if (!document.hidden) syncLive();
  });
  liveTimer = setTimeout(syncLive, 5000);
}
document.querySelectorAll("[data-pair]").forEach((slider) => {
  const number = document.getElementById(slider.dataset.pair);
  slider.addEventListener("input", () => (number.value = slider.value));
  number.addEventListener("input", () => (slider.value = number.value));
});
const provider = document.querySelector("#image-provider");
if (provider) {
  const tags = document.querySelector("#image-tag"),
    status = document.querySelector("#catalog-status");
  let requestId = 0;
  const refresh = async () => {
    const id = ++requestId;
    tags.replaceChildren();
    tags.disabled = true;
    status.textContent = tr("공식 목록 조회 중");
    try {
      const response = await fetch("/api/images/" + provider.value);
      if (!response.ok) throw Error();
      const d = await response.json();
      if (id !== requestId) return;
      for (const item of d.tags) {
        const option = document.createElement("option");
        option.value = item.tag;
        option.textContent = item.tag;
        tags.append(option);
      }
      tags.disabled = !d.tags.length;
      status.textContent = d.error
        ? tr(d.error)
        : tr(d.stale ? "캐시된 목록" : "공식 목록") + " · " + d.tags.length;
    } catch (e) {
      status.textContent = tr("공식 목록 조회 실패");
    }
  };
  provider.addEventListener("change", refresh);
  refresh();
}
const jobs = document.querySelector("#backup-jobs");
if (jobs) {
  let timer;
  async function refreshJobs() {
    if (document.hidden) return;
    try {
      const res = await fetch("/api/catalog");
      if (res.ok) {
        const d = await res.json();
        const found = d.jobs.filter((j) => j.lab === jobs.dataset.lab);
        if (found.length)
          jobs.replaceChildren(
            ...found.map((j) => {
              const p = document.createElement("p");
              p.textContent = j.time + " · " + j.state + " · " + tr(j.message);
              if (j.path) {
                const code = document.createElement("code");
                code.textContent = j.path;
                p.append(code);
              }
              return p;
            }),
          );
      }
    } finally {
      timer = setTimeout(refreshJobs, 5000);
    }
  }
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden) refreshJobs();
  });
  timer = setTimeout(refreshJobs, 5000);
}

const resourceUser = document.querySelector("[data-resource-user]");
if (resourceUser) {
  const cpu = document.querySelector("#cpu-value"),
    ram = document.querySelector("#ram-value");
  const preview = () => {
    document.querySelector("#resource-preview").textContent =
      resourceUser.value +
      " → CPU " +
      cpu.value +
      " / RAM " +
      ram.value +
      " GiB";
  };
  resourceUser.addEventListener("change", () => {
    cpu.value = resourceUser.selectedOptions[0].dataset.cpu;
    ram.value = resourceUser.selectedOptions[0].dataset.ram;
    cpu.dispatchEvent(new Event("input"));
    ram.dispatchEvent(new Event("input"));
    preview();
  });
  cpu.addEventListener("input", preview);
  ram.addEventListener("input", preview);
  document
    .querySelectorAll("[data-pair]")
    .forEach((s) => s.addEventListener("input", preview));
  preview();
}
