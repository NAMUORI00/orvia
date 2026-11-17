(() => {
  const root = document.querySelector(".user-limit-comparison"),
    select = document.querySelector("[data-resource-user]");
  if (!root || !select) return;
  const cpu = document.getElementById("cpu-value"),
    ram = document.getElementById("ram-value"),
    scopeSelect = document.querySelector("[data-limit-scope]"),
    form = select.form;
  const trText = (s) => (typeof tr === "function" ? tr(s) : s);

  function render() {
    const isAll = scopeSelect?.value === "all";
    let impact = "변경 없음";
    let allValid = true;
    let anyChanged = false;
    let anyReleasing = false;
    let anyShrinking = false;

    root.querySelectorAll("[data-limit-user]").forEach((card) => {
      const selected = isAll || card.dataset.limitUser === select.value;
      card.classList.toggle("selected", selected);
      card
        .querySelector("[data-select-limit-user]")
        .setAttribute("aria-pressed", String(selected));
      const oldCpu = Number(card.dataset.cpu),
        oldRam = Number(card.dataset.ram);
      const newCpu = selected ? Number(cpu.value) : oldCpu,
        newRam = selected ? Number(ram.value) : oldRam;
      const valid =
        !selected ||
        (cpu.value !== "" &&
          ram.value !== "" &&
          cpu.validity.valid &&
          ram.validity.valid);
      const changed = selected && (newCpu !== oldCpu || newRam !== oldRam);
      card.querySelector(".limit-edit-state").textContent = trText(
        selected ? "편집 대상" : "유지",
      );
      card.classList.toggle("has-changes", changed);

      for (const [kind, before, after, max, unit] of [
        ["cpu", oldCpu, newCpu, Number(root.dataset.cpuTotal), trText("코어")],
        ["ram", oldRam, newRam, Number(root.dataset.ramTotal), "GiB"],
      ]) {
        for (const [side, value] of [
          ["before", before],
          ["after", after],
        ]) {
          const ok = side === "before" || valid,
            bar = card.querySelector(
              '[data-limit-bar="' + kind + "-" + side + '"]',
            );
          card.querySelector(
            '[data-limit-value="' + kind + "-" + side + '"]',
          ).textContent = !ok
            ? "—"
            : value === 0
              ? trText("제한 없음")
              : value.toLocaleString() + " " + unit;
          bar.classList.toggle("unlimited", ok && value === 0);
          const pct = !ok
            ? 0
            : value === 0
              ? 100
              : Math.min(100, Math.max(0, (value / max) * 100));
          bar.querySelector(".limit-track-fill")?.setAttribute("width", pct.toFixed(1));
        }
      }

      if (selected) {
        if (!valid) allValid = false;
        if (changed) anyChanged = true;
        if ((oldCpu > 0 && newCpu === 0) || (oldRam > 0 && newRam === 0)) {
          anyReleasing = true;
        } else if (newRam > 0 && (oldRam === 0 || newRam < oldRam)) {
          anyShrinking = true;
        }
      }
    });

    impact = !allValid
      ? "입력값 확인 필요"
      : !anyChanged
        ? "변경 없음"
        : anyReleasing
          ? "한도 해제 · 환경 재생성"
          : anyShrinking
            ? "메모리 축소 · 재시작 필요"
            : "한도 변경 · 재시작 없음";
    root.querySelector("[data-limit-impact]").textContent =
      (isAll ? trText("연구실 전체") : select.value) + " · " + trText(impact);
  }

  form.addEventListener("input", render);
  form.addEventListener("change", render);
  root.querySelectorAll("[data-select-limit-user]").forEach((button) => {
    button.onclick = () => {
      if (scopeSelect) scopeSelect.value = "one";
      select.value = button.dataset.selectLimitUser;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    };
  });
  root.querySelector("[data-reset-user-limits]").onclick = () => {
    select.dispatchEvent(new Event("change", { bubbles: true }));
    render();
  };
  render();
})();
