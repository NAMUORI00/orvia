(() => {
  const approved = new WeakSet();
  const bound = new WeakSet();
  const SVG_NS = "http://www.w3.org/2000/svg";

  const translate = (value) => (typeof tr === "function" ? tr(value) : value);

  const node = (tag, value, cls, raw = false) => {
    const n = document.createElement(tag);
    if (value !== undefined && value !== null) {
      n.textContent = raw ? String(value) : translate(String(value));
    }
    if (cls) n.className = cls;
    return n;
  };

  function makeIcon(kind) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.85");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const addPath = (d) => {
      const p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      svg.append(p);
    };
    const addCircle = (cx, cy, r) => {
      const c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("cx", String(cx));
      c.setAttribute("cy", String(cy));
      c.setAttribute("r", String(r));
      svg.append(c);
    };
    if (kind === "warn") {
      addPath("M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z");
      addPath("M12 9v4");
      addPath("M12 17h.01");
    } else if (kind === "crit") {
      addPath("M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86L7.86 2Z");
      addPath("M12 8v4");
      addPath("M12 16h.01");
    } else if (kind === "safe") {
      addPath("M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z");
      addPath("m9 12 2 2 4-4");
    } else if (kind === "close") {
      addPath("M18 6 6 18");
      addPath("m6 6 12 12");
    } else {
      addCircle(12, 12, 10);
      addPath("M12 16v-4");
      addPath("M12 8h.01");
    }
    return svg;
  }

  function appendCallout(listEl, tone, heading, text, rawHeading = false, rawText = false) {
    const box = document.createElement("div");
    box.className = "review-callout is-" + tone;
    const iconWrap = document.createElement("span");
    iconWrap.className = "review-callout-icon";
    iconWrap.append(makeIcon(tone));
    const body = document.createElement("div");
    body.className = "review-callout-body";
    body.append(
      node("strong", heading, "", rawHeading),
      node("p", text, "", rawText),
    );
    box.append(iconWrap, body);
    listEl.append(box);
  }

  function handleSubmit(event) {
    const form = event.currentTarget;
    if (form.id === "create-lab-form") {
      const wizardSubmit = document.getElementById("wizard-submit");
      if (wizardSubmit && wizardSubmit.hidden) return;
      const step2 = form.querySelector('[data-wizard-step="2"]');
      if (step2) {
        for (const inp of step2.querySelectorAll("input,select")) {
          if (!inp.checkValidity()) {
            const det = inp.closest("details");
            if (det) det.open = true;
            event.preventDefault();
            inp.reportValidity();
            return;
          }
        }
      }
    }
    if (approved.has(form)) {
      approved.delete(form);
      return;
    }
    event.preventDefault();

    const fields = new FormData(form);
    const action =
      String(fields.get("action") || "") ||
      (fields.get("plan")
        ? "provision_apply"
        : form.id === "create-lab-form" || form.action.endsWith("/provision/prepare")
          ? "provision_prepare"
          : "");

    const dialog = document.createElement("dialog");
    dialog.className = "review-dialog";

    const head = document.createElement("div");
    head.className = "review-head";
    const headLeft = document.createElement("div");
    headLeft.className = "review-head-main";
    const headIcon = document.createElement("span");
    headIcon.className = "review-head-icon";
    const title = node("h2", "변경 확인");
    title.id = "change-review-title";
    dialog.setAttribute("aria-labelledby", title.id);

    const subtitle = form.dataset.labTitle
      ? node("span", form.dataset.labTitle, "review-head-sub", true)
      : null;
    const headTitleWrap = document.createElement("div");
    headTitleWrap.append(title);
    if (subtitle) headTitleWrap.append(subtitle);
    headLeft.append(headIcon, headTitleWrap);

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "review-close-btn";
    closeBtn.setAttribute("aria-label", translate("닫기"));
    closeBtn.append(makeIcon("close"));
    head.append(headLeft, closeBtn);
    dialog.append(head);

    const list = document.createElement("dl");
    list.className = "review-summary-dl";
    const add = (label, value, rawVal = false) =>
      list.append(node("dt", label), node("dd", value, "", rawVal));

    if (form.dataset.labTitle || fields.get("lab")) {
      add("대상 연구실", form.dataset.labTitle || fields.get("lab"), true);
    }
    if (form.dataset.impact) add("적용 방식", form.dataset.impact);
    if (form.dataset.affectedAccounts) {
      add("영향받는 계정", form.dataset.affectedAccounts, true);
    }

    if (fields.get("scope") === "all") {
      add("적용 대상", "연구실 전체 계정");
    }

    for (const [key, label] of [
      ["user", "대상 사용자"],
      ["new_user", "새 계정 ID"],
      ["container_name", "컨테이너 이름"],
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
        let rawVal = true;
        if (key === "cpu") {
          if (Number(val) === 0) {
            display = translate("제한 없음");
          } else {
            display = val + " " + translate("코어");
          }
        } else if (key === "ram") {
          display = Number(val) === 0 ? translate("제한 없음") : val + " GiB";
        } else if (key === "size_gb" || key === "storage_gb") {
          display = val + " GB";
        }
        add(label, display, rawVal);
      }
    }

    if (fields.getAll("gpu_selection").length) {
      add(
        "배정 GPU",
        fields
          .getAll("gpu_selection")
          .map((v) => "GPU " + v)
          .join(", "),
        true,
      );
    } else if (fields.get("gpu_index")) {
      add("배정 GPU", "GPU " + fields.get("gpu_index"), true);
    }

    if (fields.get("image_provider") && fields.get("image_tag")) {
      add(
        "개발환경 이미지",
        (fields.get("image_provider") === "pytorch" ? "NVIDIA PyTorch" : "NVIDIA CUDA") +
          ":" +
          fields.get("image_tag"),
        true,
      );
    }

    if (fields.get("permission_profile")) {
      add(
        "권한 프로필",
        fields.get("permission_profile") === "container_admin"
          ? "컨테이너 관리자"
          : "표준 사용자",
      );
    }
    if (form.dataset.current) add("현재 설정", form.dataset.current, true);

    dialog.append(list);

    // Dynamic contextual warning callouts
    const callouts = document.createElement("div");
    callouts.className = "review-callout-list";
    let needsAckShared = false;
    let needsAckDowntime = false;
    let blockSubmit = false;
    let primaryTone = "safe";

    if (action === "gpu_reconfigure") {
      const checkedGpus = [...form.querySelectorAll('input[name="gpu_selection"]:checked')];
      if (!checkedGpus.length) {
        blockSubmit = true;
        primaryTone = "crit";
        appendCallout(
          callouts,
          "crit",
          "GPU 선택이 필요합니다",
          "최소 1개 이상의 GPU를 선택한 뒤 변경을 적용할 수 있습니다.",
        );
      } else {
        primaryTone = "warn";
        needsAckDowntime = true;
        appendCallout(
          callouts,
          "warn",
          "실행 작업 일시 중단 안내",
          "이 연구실의 SSH 접속과 실행 중인 작업이 종료된 뒤 새 GPU 구성으로 컨테이너를 시작합니다.",
        );
        const sharedDetails = [];
        for (const inp of checkedGpus) {
          const ownerTitle = (inp.dataset.ownerTitle || "").trim();
          const busy = inp.dataset.gpuBusy === "yes";
          if (ownerTitle || busy) {
            const note = ownerTitle ? ownerTitle : translate("실행 작업 사용 중");
            sharedDetails.push("GPU " + inp.value + " (" + note + ")");
          }
        }
        if (sharedDetails.length) {
          needsAckShared = true;
          primaryTone = "crit";
          appendCallout(
            callouts,
            "crit",
            translate("타 연구실 배정 · 사용 중 GPU 공유 경고"),
            translate("선택한 GPU가 다른 연구실 또는 현재 작업과 자원을 공유합니다:") +
              " " +
              sharedDetails.join(", "),
            true,
            true,
          );
        }
        appendCallout(
          callouts,
          "safe",
          "개인 폴더 및 계정 설정 보존",
          "/home/<ID> 영구 저장공간과 기존 계정·SSH 포트는 그대로 유지됩니다.",
        );
      }
    } else if (action === "provision_prepare") {
      const picked = form.querySelector('input[name="gpu_index"]:checked');
      if (picked && (picked.dataset.ownerTitle || picked.dataset.gpuBusy === "yes")) {
        needsAckShared = true;
        primaryTone = "warn";
        const reason = picked.dataset.ownerTitle
          ? picked.dataset.ownerTitle
          : translate("실행 작업 사용 중");
        appendCallout(
          callouts,
          "crit",
          translate("이미 배정된 GPU 공유 사용 경고"),
          "GPU " + picked.value + " (" + reason + ") — " + translate("선택한 GPU를 새 연구실과 함께 공유하게 됩니다."),
          true,
          true,
        );
      }
      appendCallout(
        callouts,
        "safe",
        "기존 연구실 무중단 보호",
        "표시된 구성으로 생성 계획만 준비하며 현재 실행 중인 다른 연구실 컨테이너에는 영향을 주지 않습니다.",
      );
    } else if (action === "resources") {
      const transition = form.dataset.limitTransition || "live";
      if (transition === "release") {
        primaryTone = "warn";
        needsAckDowntime = true;
        appendCallout(
          callouts,
          "warn",
          "자원 한도 해제 · 컨테이너 재생성 안내",
          "한도를 제한 없음으로 해제하려면 컨테이너를 재생성해야 하므로 현재 접속과 실행 작업이 종료됩니다. 저장 자료는 유지됩니다.",
        );
      } else if (transition === "shrink") {
        primaryTone = "warn";
        needsAckDowntime = true;
        appendCallout(
          callouts,
          "warn",
          "메모리 상한 적용 · 재시작 안내",
          "메모리 한도를 축소하거나 새로 설정하면 컨테이너 재시작이 필요하며 실행 중인 작업이 종료됩니다. 저장 자료는 유지됩니다.",
        );
      } else {
        primaryTone = "safe";
        appendCallout(
          callouts,
          "safe",
          "무중단 실시간 한도 반영",
          "컨테이너 재시작이나 작업 중단 없이 CPU·메모리 한도를 즉시 반영합니다.",
        );
      }
    } else if (action === "lab_restart" || action === "maintenance_restart") {
      primaryTone = "warn";
      needsAckDowntime = true;
      appendCallout(
        callouts,
        "warn",
        "접속 및 실행 작업 종료 안내",
        "연구실 컨테이너의 모든 SSH 세션과 CPU 실행 작업이 종료된 뒤 다시 시작됩니다.",
      );
      appendCallout(
        callouts,
        "safe",
        "GPU 작업 보호 및 저장 자료 유지",
        "적용 직전 GPU 사용량이 감지되면 재시작을 자동 중단하며 계정과 /home/<ID> 영구 자료는 유지됩니다.",
      );
    } else if (action === "maintenance_recreate") {
      primaryTone = "warn";
      needsAckDowntime = true;
      appendCallout(
        callouts,
        "warn",
        "실행 작업 종료 및 동일 구성 재생성",
        "이 컨테이너를 사용하는 모든 계정의 접속과 실행 작업이 종료됩니다.",
      );
      appendCallout(
        callouts,
        "safe",
        "이전 환경 보관 및 자료 유지",
        "현재 이미지와 저장 연결은 유지되며 이전 컨테이너는 복구용으로 보관됩니다.",
      );
    } else if (action === "lab_separate" || action === "lab_share") {
      primaryTone = "warn";
      needsAckDowntime = true;
      appendCallout(
        callouts,
        "warn",
        "컨테이너 아키텍처 전환 및 접속 포트 변경",
        "전환 중 접속이 종료되며 SSH 포트 구성이 변경됩니다. GPU나 사용자 프로세스가 실행 중이면 안전을 위해 자동 중단됩니다.",
      );
      appendCallout(
        callouts,
        "safe",
        "계정 · 비밀번호 · 개인 파일 보존",
        "모든 계정과 /home/<ID> 개인 파일은 손실 없이 이전되며 이전 컨테이너는 복구용으로 보관됩니다.",
      );
    } else if (action === "environment_apply") {
      primaryTone = "warn";
      needsAckDowntime = true;
      appendCallout(
        callouts,
        "warn",
        "공식 이미지 교체 및 환경 재생성",
        "공식 이미지 준비 완료 후 컨테이너를 재생성하며 실행 중인 작업이 종료됩니다. 시스템 기본 패키지는 새 이미지 구성으로 바뀝니다.",
      );
      appendCallout(
        callouts,
        "safe",
        "영구 저장자료 및 계정 유지",
        "기존 계정과 /home/<ID> 저장 자료는 그대로 유지됩니다.",
      );
    } else if (action === "backup") {
      primaryTone = "info";
      appendCallout(
        callouts,
        "info",
        "무중단 라이브 백업 일관성 안내",
        "컨테이너를 정지하지 않고 백업하므로 실행 중 쓰기가 발생하는 파일은 동일 시점 일관성이 보장되지 않습니다. 주요 학습 저장 완료 후 실행하세요.",
      );
    } else if (action === "account_delete") {
      primaryTone = "crit";
      appendCallout(
        callouts,
        "crit",
        "계정 및 개인 폴더 삭제 경고",
        "복구용 백업을 먼저 검증한 뒤 선택한 계정의 로그인과 /home/<ID> 폴더를 삭제합니다. 공용 컨테이너와 다른 구성원의 자료는 유지됩니다.",
      );
    } else if (form.dataset.review) {
      const safeTone = form.dataset.reviewTone === "safe";
      primaryTone = safeTone ? "safe" : "info";
      appendCallout(
        callouts,
        primaryTone,
        safeTone ? "무중단 안전 변경" : "변경 영향 안내",
        form.dataset.review,
      );
    }

    headIcon.classList.add("is-" + primaryTone);
    headIcon.append(makeIcon(primaryTone));
    dialog.append(callouts);

    const buttons = document.createElement("div");
    buttons.className = "review-actions";
    const back = node("button", "취소"),
      apply = node("button", form.dataset.submitLabel || "확인 후 적용");
    back.type = apply.type = "button";
    back.className = "secondary";
    if (primaryTone === "crit" || action === "account_delete") {
      apply.className = "danger";
    }
    if (blockSubmit) apply.disabled = true;
    buttons.append(back, apply);
    dialog.append(buttons);

    closeBtn.addEventListener("click", () => dialog.close());
    back.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove());
    apply.addEventListener("click", () => {
      if (form.elements.ack_shared) {
        form.elements.ack_shared.value = needsAckShared ? "yes" : "";
      }
      if (form.elements.ack_downtime) {
        if (action === "resources") {
          form.elements.ack_downtime.value = needsAckDowntime ? "yes" : "";
        } else if (needsAckDowntime) {
          form.elements.ack_downtime.value = "yes";
        }
      }
      if (
        form.elements.ack_recreate &&
        [
          "gpu_reconfigure",
          "maintenance_recreate",
          "lab_separate",
          "lab_share",
          "environment_apply",
        ].includes(action)
      ) {
        form.elements.ack_recreate.value = "yes";
      }
      if (form.elements.ack_environment && action === "environment_apply") {
        form.elements.ack_environment.value = "yes";
      }
      if (form.elements.ack_delete && action === "account_delete") {
        form.elements.ack_delete.value = "yes";
      }
      if (form.elements.consistency && action === "backup") {
        form.elements.consistency.value = "live";
      }
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
