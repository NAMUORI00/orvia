(() => {
  const approved = new WeakSet();
  document.querySelectorAll("form[data-review]").forEach((form) =>
    form.addEventListener("submit", (event) => {
      if (approved.has(form)) {
        approved.delete(form);
        return;
      }
      event.preventDefault();
      const dialog = document.createElement("dialog");
      dialog.className = "review-dialog";
      const node = (tag, value) => {
        const n = document.createElement(tag);
        n.textContent = typeof tr === "function" ? tr(value) : value;
        return n;
      };
      const title = node("h2", "변경 확인");
      dialog.append(title);
      title.id = "change-review-title";
      dialog.setAttribute("aria-labelledby", title.id);
      const fields = new FormData(form),
        list = document.createElement("dl");
      const add = (label, value) =>
        list.append(node("dt", label), node("dd", String(value)));
      add("대상 연구실", form.dataset.labTitle || fields.get("lab"));
      if (form.dataset.impact) add("적용 방식", form.dataset.impact);
      for (const [key, label] of [
        ["user", "대상 사용자"],
        ["title", "연구실 이름"],
        ["cpu", "CPU 한도"],
        ["ram", "메모리 한도"],
        ["size_gb", "변경 용량"],
        ["storage_name", "저장 폴더명"],
      ])
        if (fields.get(key))
          add(
            label,
            fields.get(key) +
              (key === "cpu"
                ? " CPU"
                : key === "ram"
                  ? " GiB"
                  : key === "size_gb"
                    ? " GB"
                    : ""),
          );
      if (fields.getAll('gpu_selection').length) add('배정 GPU', fields.getAll('gpu_selection').map(v=>'GPU '+v).join(', '));
      if (form.dataset.current) add("현재 설정", form.dataset.current);
      dialog.append(list, node("p", form.dataset.review));
      const buttons = document.createElement("div");
      buttons.className = "review-actions";
      const back = node("button", "취소"),
        apply = node("button", form.dataset.submitLabel || "적용");
      back.type = apply.type = "button";
      back.className = "secondary";
      buttons.append(back, apply);
      dialog.append(buttons);
      back.addEventListener("click", () => dialog.close());
      dialog.addEventListener("close", () => dialog.remove());
      apply.addEventListener("click", () => {
        approved.add(form);
        dialog.close();
        form.requestSubmit();
      });
      document.body.append(dialog);
      dialog.showModal();
      back.focus();
    }),
  );
})();
