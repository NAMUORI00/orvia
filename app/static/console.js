let messages = {},
  translationPattern = null;
const tr = (text) =>
  typeof text === "string" && translationPattern
    ? text.replace(translationPattern, (m) => messages[m])
    : text;

window.orviaTrReady = document.body.classList.contains("unauth")
  ? Promise.resolve({})
  : fetch("/api/translations")
      .then((r) => (r.ok ? r.json() : {}))
      .then((d) => {
        messages = d || {};
        const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const keys = Object.keys(messages);
        if (!keys.length) return messages;
        translationPattern = new RegExp(
          keys
            .sort((a, b) => b.length - a.length)
            .map(escape)
            .join("|"),
          "g",
        );
        return messages;
      })
      .catch(() => ({}));

let toastTimer = null;
window.orviaToast = (message) => {
  const el = document.getElementById("orvia-toast");
  if (!el || !message) return;
  el.textContent = tr(message);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, 2600);
};

window.orviaCopy = async (text, successMsg) => {
  const value = String(text || "");
  if (!value) return;
  let copied = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      copied = true;
    }
  } catch (_) {
    copied = false;
  }
  if (!copied) {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.className = "sr-copy-buffer";
    document.body.append(area);
    area.select();
    try {
      copied = document.execCommand("copy");
    } catch (_) {
      copied = false;
    }
    area.remove();
  }
  window.orviaToast(
    copied ? successMsg || "클립보드에 복사했습니다." : "복사를 완료하지 못했습니다. 직접 선택해 복사하세요.",
  );
};

window.orviaSyncLangLinks = () => {
  const next = location.pathname + location.search;
  document.querySelectorAll("a.language-link[data-lang-code]").forEach((a) => {
    a.href =
      "/language?lang=" +
      encodeURIComponent(a.dataset.langCode) +
      "&next=" +
      encodeURIComponent(next);
  });
};

document
  .querySelector("[data-refresh]")
  ?.addEventListener("click", () => location.reload());

const helpBanner = document.getElementById("help-banner");
const helpToggle = document.querySelector("[data-help-toggle]");
if (helpBanner && helpToggle) {
  const setHelp = (open) => {
    helpBanner.hidden = !open;
    helpToggle.setAttribute("aria-expanded", String(open));
    document.getElementById("twin")?.classList.toggle("help-active", open);
  };
  helpToggle.addEventListener("click", () => setHelp(helpBanner.hidden));
  document
    .querySelector("[data-help-close]")
    ?.addEventListener("click", () => setHelp(false));
}

document.querySelectorAll("[data-pair]").forEach((slider) => {
  const number = document.getElementById(slider.dataset.pair);
  if (!number) return;
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
    } catch (_) {
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
              p.textContent = j.time + " · " + tr(j.state) + " · " + tr(j.message);
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
    ram = document.querySelector("#ram-value"),
    scopeSelect = document.querySelector("[data-limit-scope]"),
    userRow = document.querySelector("[data-limit-user-field]");
  const preview = () => {
    const isAll = scopeSelect?.value === "all";
    if (userRow) userRow.hidden = isAll;
    const targetLabel = isAll ? tr("연구실 전체") : resourceUser.value;
    document.querySelector("#resource-preview").textContent =
      targetLabel +
      " → CPU " +
      (Number(cpu.value) === 0 ? tr("제한 없음") : cpu.value + " " + tr("코어")) +
      " / RAM " +
      (Number(ram.value) === 0 ? tr("제한 없음") : ram.value + " GiB");
  };
  scopeSelect?.addEventListener("change", preview);
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
