(() => {
  document.querySelectorAll("[data-storage-root]").forEach((input) => {
    const preview = input.form.querySelector("[data-storage-preview]");
    input.addEventListener("input", () => {
      preview.textContent = /^[a-z][a-z0-9_-]{1,31}$/.test(input.value)
        ? input.dataset.storageRoot.replace(/\/$/, "") + "/" + input.value
        : typeof tr === "function"
          ? tr("유효한 폴더명을 입력하세요.")
          : "유효한 폴더명을 입력하세요.";
    });
  });
  const form = document.getElementById("create-lab-form");
  if (form) {
    form.noValidate = true;
    let step = 0;
    const panes = [...form.querySelectorAll("[data-wizard-step]")];
    const id = form.elements.id;
    id.value =
      "lab-" +
      Array.from(crypto.getRandomValues(new Uint8Array(4)), (n) =>
        n.toString(16).padStart(2, "0"),
      ).join("");
    function blueprint() {
      const official = form.elements.image_mode.value === "official";
      const providerValue = form.elements.image_provider.value;
      const image = official
        ? (providerValue === "cuda" ? "NVIDIA CUDA" : "NVIDIA PyTorch") + " · " + (form.elements.image_tag.value || tr("이미지 버전 선택"))
        : form.querySelector("[name=source_container]:checked")?.closest("label").querySelector("strong").textContent || tr("이미지 선택");
      const values = {image, gpu: form.elements.gpu_index.value ? "GPU " + form.elements.gpu_index.value : "—", storage: Number(form.elements.storage_gb.value).toLocaleString() + " GB", user: form.elements.new_user.value || tr("계정 입력")};
      for (const [key,value] of Object.entries(values)) {
        const el = document.getElementById("blueprint-" + key);
        if (el.textContent !== value) {
          el.textContent = value;
          if (!matchMedia("(prefers-reduced-motion: reduce)").matches)
            el.closest(".blueprint-node").animate([{backgroundColor:"#c7ede4"},{backgroundColor:"#f3faf8"}],{duration:450});
        }
      }
    }
    form.addEventListener("input", blueprint);
    form.addEventListener("change", blueprint);
    function valid() {
      if (
        step === 0 &&
        form.elements.image_mode.value === "official" &&
        (form.elements.image_tag.disabled || !form.elements.image_tag.value)
      ) {
        document.getElementById("provision-catalog-status").textContent =
          tr("사용할 이미지 버전을 선택하세요.");
        return false;
      }
      for (const input of panes[step].querySelectorAll("input,select")) {
        if (!input.checkValidity()) {
          const detail = input.closest("details");
          if (detail) detail.open = true;
          input.reportValidity();
          return false;
        }
      }
      return true;
    }
    function show(move = false) {
      blueprint();
      if (move) form.closest(".provision-wizard").scrollIntoView({block: "start"});
      panes.forEach((p, i) => (p.hidden = i !== step));
      document.querySelectorAll("[data-step-label]").forEach((p, i) => {
        p.classList.toggle("active", i === step);
        p.setAttribute("aria-current", i === step ? "step" : "false");
      });
      document.getElementById("wizard-back").hidden = step === 0;
      document.getElementById("wizard-next").hidden = step === 2;
      document.getElementById("wizard-submit").hidden = step !== 2;
      if (step === 2) {
        const summary = document.getElementById("creation-summary");
        summary.replaceChildren();
        const selected = form.querySelector("[name=source_container]:checked");
        const entries = [
          ["연구실 이름", form.elements.title.value],
          [
            "사용할 Docker 이미지",
            form.elements.image_mode.value === "official"
              ? form.elements.image_provider.selectedOptions[0].textContent +
                " · " +
                form.elements.image_tag.value
              : selected?.closest("label").querySelector("strong")
                  .textContent || "N/A",
          ],
          ["GPU", form.elements.gpu_index.value],
          ["저장 용량 (GB)", form.elements.storage_gb.value],
        ];
        for (const [label, value] of entries) {
          const row = document.createElement("p");
          row.textContent = tr(label) + " · " + value;
          summary.append(row);
        }
      }
    }
    document.getElementById("wizard-next").onclick = () => {
      if (valid()) {
        step++;
        show(true);
      }
    };
    document.getElementById("wizard-back").onclick = () => {
      step--;
      show(true);
    };
    form.addEventListener("submit", (e) => {
      if (step !== 2) {
        e.preventDefault();
        if (valid()) {
          step++;
          show(true);
        }
      } else if (!valid()) e.preventDefault();
    });
    form.querySelectorAll("[data-size]").forEach(
      (button) =>
        (button.onclick = () => {
          form.elements.storage_gb.value = button.dataset.size;
          document.getElementById("storage-range").value = button.dataset.size;
          blueprint();
        }),
    );
    const slider = document.getElementById("storage-range"),
      storage = form.elements.storage_gb;
    form
      .querySelectorAll("[data-size]")
      .forEach(
        (button) =>
          (button.disabled = Number(button.dataset.size) > Number(storage.max)),
      );
    slider.oninput = () => (storage.value = slider.value);
    storage.oninput = () => (slider.value = storage.value);
    let dragged = null;
    const cards = [...form.querySelectorAll("[data-drag-kind]")];
    function selection(kind) {
      const name = kind === "image" ? "source_container" : "gpu_index";
      const choice = form.querySelector("[name=" + name + "]:checked");
      const target = document.getElementById(kind + "-drop");
      if (choice) {
        target.textContent =
          (kind === "image" ? "▣ " : "▥ ") +
          choice.closest("label").querySelector("strong").textContent +
          " · " +
          tr("선택됨");
        target.classList.add("selected");
      }
    }
    cards.forEach((card) => {
      card.addEventListener("dragstart", (e) => {
        dragged = card;
        e.dataTransfer.effectAllowed = "copy";
        e.dataTransfer.setData("text/plain", card.querySelector("input").value);
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => {
        dragged = null;
        card.classList.remove("dragging");
        form
          .querySelectorAll("[data-drop-kind]")
          .forEach((z) => z.classList.remove("drag-over"));
      });
      card
        .querySelector("input")
        .addEventListener("change", () => selection(card.dataset.dragKind));
    });
    form.querySelectorAll("[data-drop-kind]").forEach((zone) => {
      zone.addEventListener("dragover", (e) => {
        if (dragged?.dataset.dragKind === zone.dataset.dropKind) {
          e.preventDefault();
          zone.classList.add("drag-over");
        }
      });
      zone.addEventListener("dragleave", () =>
        zone.classList.remove("drag-over"),
      );
      zone.addEventListener("drop", (e) => {
        e.preventDefault();
        zone.classList.remove("drag-over");
        if (dragged?.dataset.dragKind !== zone.dataset.dropKind) return;
        dragged.querySelector("input").checked = true;
        selection(zone.dataset.dropKind);
        blueprint();
      });
    });
    selection("image");
    selection("gpu");
    const provider = document.getElementById("provision-provider"),
      tag = document.getElementById("provision-tag"),
      catalogStatus = document.getElementById("provision-catalog-status");
    let catalogRequest = 0;
    let preferredTag =
      form.querySelector("[data-base-tag]")?.dataset.baseTag || "";
    function selectedImage() {
      const repo = provider.value === "cuda" ? "nvidia/cuda" : "nvcr.io/nvidia/pytorch";
      blueprint();
      document.getElementById("selected-official-image").textContent =
        repo + (tag.value ? ":" + tag.value : " · " + tr("이미지 버전 선택"));
      form.querySelectorAll("[data-base-tag]").forEach((button) => {
        const active = button.dataset.baseProvider === provider.value && button.dataset.baseTag === tag.value;
        button.setAttribute("aria-pressed", String(active));
      });
    }
    tag.onchange = () => { preferredTag = tag.value; selectedImage(); };
    async function loadTags() {
      const seq = ++catalogRequest;
      tag.replaceChildren();
      tag.disabled = true;
      selectedImage();
      catalogStatus.textContent = tr("공식 목록 조회 중");
      try {
        const res = await fetch("/api/images/" + provider.value);
        if (!res.ok) throw Error();
        const data = await res.json();
        if (seq !== catalogRequest) return;
        const items = data.tags.filter(
          (x) =>
            provider.value !== "cuda" || x.tag.toLowerCase().includes("ubuntu"),
        );
        form.querySelectorAll("[data-base-tag]").forEach((button) => {
          if (
            button.dataset.baseProvider === provider.value &&
            !items.some((x) => x.tag === button.dataset.baseTag)
          )
            items.unshift({ tag: button.dataset.baseTag });
        });
        for (const item of items) {
          const o = document.createElement("option");
          o.value = item.tag;
          o.textContent = item.tag;
          tag.append(o);
        }
        tag.disabled =
          form.elements.image_mode.value !== "official" || !items.length;
        if ([...tag.options].some((o) => o.value === preferredTag))
          tag.value = preferredTag;
        selectedImage();
        catalogStatus.textContent =
          tr(data.error || (data.stale ? "캐시된 목록" : "공식 목록")) +
          " · " +
          items.length;
      } catch (_) {
        if (seq !== catalogRequest) return;
        selectedImage();
        catalogStatus.textContent = tr("공식 목록 조회 실패");
      }
    }
    function imageMode() {
      const official = form.elements.image_mode.value === "official";
      document.getElementById("registered-images").hidden = official;
      document.getElementById("official-images").hidden = !official;
      form.querySelectorAll("[name=source_container]").forEach((r) => {
        r.disabled = official;
        r.required = !official;
      });
      provider.disabled = !official;
      tag.disabled = !official;
      tag.required = official;
      if (official) loadTags();
      else catalogRequest++;
    }
    form
      .querySelectorAll("[name=image_mode]")
      .forEach((r) => (r.onchange = imageMode));
    provider.onchange = () => {
      preferredTag = "";
      loadTags();
    };
    form.querySelectorAll("[data-base-tag]").forEach(
      (button) =>
        (button.onclick = () => {
          preferredTag = button.dataset.baseTag;
          provider.value = button.dataset.baseProvider;
          loadTags();
        }),
    );
    document
      .getElementById("advanced-images")
      .addEventListener("toggle", (e) => {
        if (!e.target.open && form.elements.image_mode.value === "registered") {
          form.querySelector("[name=image_mode][value=official]").checked =
            true;
          imageMode();
        }
      });
    imageMode();
    show();
  }
  async function update() {
    if (!document.hidden) {
      try {
        const response = await fetch("/api/provision");
        if (response.ok) {
          const data = await response.json();
          const root = document.getElementById("provision-jobs");
          root.replaceChildren(
            ...data.jobs.map((job) => {
              const line = document.createElement("div");
              line.className = "provision-job";
              const symbol = document.createElement("span");
              symbol.className = "job-symbol";
              symbol.textContent = job.state === "complete" ? "✓" : job.state === "failed" ? "!" : "◷";
              symbol.setAttribute("aria-hidden", "true");
              const body = document.createElement("div"), title = document.createElement("strong"), detail = document.createElement("small");
              title.textContent = job.lab + " · " + tr(job.state);
              detail.textContent = tr(job.message);
              body.append(title, detail); line.append(symbol, body);
              return line;
            }),
          );
        }
      } catch (_) {
        /* Keep the last visible result on transient failure. */
      }
    }
    setTimeout(update, 5000);
  }
  setTimeout(update, 5000);
})();
