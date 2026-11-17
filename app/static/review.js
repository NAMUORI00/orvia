(() => {
  const approved = new WeakSet();
  const bound = new WeakSet();

  const translate = (value) => (typeof tr === "function" ? tr(value) : value);

  const node = (tag, value, cls) => {
    const n = document.createElement(tag);
    n.textContent = translate(String(value));
    if (cls) n.className = cls;
    return n;
  };

  function handleSubmit(event) {
    const form = event.currentTarget;
    if (approved.has(form)) {
      approved.delete(form);
      return;
    }
    event.preventDefault();
    const dialog = document.createElement("dialog");
    dialog.className = "review-dialog";
    const title = node("h2", "변경 확인");
    dialog.append(title);
    title.id = "change-review-title";
    dialog.setAttribute("aria-labelledby", title.id);

    const fields = new FormData(form),
      list = document.createElement("dl");
    const add = (label, value) =>
      list.append(node("dt", label), node("dd", value));

    if (form.dataset.labTitle || fields.get("lab")) {
      add("대상 연구실", form.dataset.labTitle || fields.get("lab"));
    }
    if (form.dataset.impact) add("적용 방식", form.dataset.impact);

    if (fields.get("scope") === "all") {
      add("적용 대상", "연구실 전체 계정");
    }

    for (const [key, label] of [
      ["user", "대상 사용자"],
      ["new_user", "새 계정 ID"],
      ["title", "연구실 이름"],
      ["cpu", "CPU 한도"],
      ["ram", "메모리 한도"],
      ["size_gb", "변경 용량"],
      ["storage_name", "저장 폴더명"],
      ["storage_gb", "공유 저장공간"],
    ]) {
      const val = fields.get(key);
      if (key === "user" && fields.get("scope") === "all") continue;
      if (val !== null && val !== "") {
        let display = String(val);
        if (key === "cpu") {
          display = Number(val) === 0 ? translate("제한 없음") : val + " CPU";
        } else if (key === "ram") {
          display = Number(val) === 0 ? translate("제한 없음") : val + " GiB";
        } else if (key === "size_gb" || key === "storage_gb") {
          display = val + " GB";
        }
        add(label, display);
      }
    }

    if (fields.getAll("gpu_selection").length) {
      add(
        "배정 GPU",
        fields
          .getAll("gpu_selection")
          .map((v) => "GPU " + v)
          .join(", "),
      );
    } else if (fields.get("gpu_index")) {
      add("배정 GPU", "GPU " + fields.get("gpu_index"));
    }

    if (fields.get("permission_profile")) {
      add(
        "권한 프로필",
        fields.get("permission_profile") === "container_admin"
          ? "컨테이너 관리자"
          : "표준 사용자",
      );
    }
    if (form.dataset.current) add("현재 설정", form.dataset.current);

    dialog.append(list);
    const reviewNote = node("p", form.dataset.review, "review-note");
    if (form.dataset.reviewTone === "safe") reviewNote.classList.add("is-safe");
    dialog.append(reviewNote);

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
  }

  window.orviaBindReview = (root = document) => {
    root.querySelectorAll("form[data-review]").forEach((form) => {
      if (bound.has(form)) return;
      bound.add(form);
      form.addEventListener("submit", handleSubmit);
    });
  };

  window.orviaBindReview(document);
})();
