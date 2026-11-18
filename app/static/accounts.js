(() => {
  const t = (s) => (typeof tr === "function" ? tr(String(s)) : String(s));
  const search = document.querySelector("[data-account-search]");
  const cards = [...document.querySelectorAll("[data-account-card]")];
  const railButtons = [...document.querySelectorAll("[data-select-account]")];
  const grid = document.querySelector(".account-card-grid");
  const hostAddr = grid?.dataset.accessHost || location.hostname;

  function syncRailSelection(activeName) {
    railButtons.forEach((btn) => {
      const selected = btn.dataset.selectAccount === activeName;
      btn.classList.toggle("is-selected", selected);
      btn.setAttribute("aria-pressed", String(selected));
    });
  }

  function focusAccount(name, scroll = true) {
    const targetCard = cards.find((c) => c.dataset.accountName === name);
    if (!targetCard) return;
    cards.forEach((c) => {
      if (c !== targetCard) c.open = false;
    });
    targetCard.open = true;
    syncRailSelection(name);
    if (scroll) {
      targetCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  railButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.selectAccount;
      focusAccount(name, true);
      if (history.replaceState) {
        history.replaceState(null, "", "#account-" + encodeURIComponent(name));
      }
    });
  });

  cards.forEach((card) => {
    // Sync segmented tabs inside each person card
    const tabBtns = [...card.querySelectorAll("[data-person-tab]")];
    const panes = [...card.querySelectorAll("[data-person-pane]")];
    tabBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.personTab;
        tabBtns.forEach((b) => {
          const on = b === btn;
          b.classList.toggle("active", on);
          b.setAttribute("aria-selected", String(on));
        });
        panes.forEach((p) => {
          p.hidden = p.dataset.personPane !== key;
        });
      });
    });

    // Check matching passwords cleanly before modal confirmation
    const pw = card.querySelector('input[name="password"]');
    const pwConfirm = card.querySelector('input[name="password_confirm"]');
    if (pw && pwConfirm) {
      const checkMatch = () => {
        pwConfirm.setCustomValidity(
          pwConfirm.value && pw.value !== pwConfirm.value
            ? t("새 비밀번호와 확인 입력이 일치하지 않습니다.")
            : "",
        );
      };
      pw.addEventListener("input", checkMatch);
      pwConfirm.addEventListener("input", checkMatch);
    }

    card.addEventListener("toggle", () => {
      if (card.open) {
        const name = card.dataset.accountName;
        cards.forEach((c) => {
          if (c !== card) c.open = false;
        });
        syncRailSelection(name);
      }
    });
  });

  search?.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    let firstVisible = null;
    cards.forEach((card) => {
      const show = !query || card.dataset.search.toLocaleLowerCase().includes(query);
      card.hidden = !show;
      if (show) {
        visible++;
        if (!firstVisible) firstVisible = card.dataset.accountName;
      }
    });
    railButtons.forEach((btn) => {
      btn.hidden = Boolean(query && !btn.dataset.search.toLocaleLowerCase().includes(query));
    });
    const empty = document.querySelector("[data-account-empty]");
    if (empty) empty.hidden = visible > 0;
    if (firstVisible && cards.every((c) => !c.open || c.hidden)) {
      focusAccount(firstVisible, false);
    }
  });

  document.querySelector("[data-open-add-account]")?.addEventListener("click", () => {
    const addBox = document.getElementById("add-account-card");
    if (!addBox) return;
    addBox.open = true;
    addBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    addBox.querySelector("input[name='new_user']")?.focus();
  });

  document.querySelectorAll("[data-copy-ssh]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const cmd = "ssh -p " + btn.dataset.port + " " + btn.dataset.user + "@" + hostAddr;
      window.orviaCopy?.(cmd, "SSH 접속 명령어를 복사했습니다.");
    });
  });

  document.querySelectorAll("[data-copy-guide]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const cmd = "ssh -p " + btn.dataset.port + " " + btn.dataset.user + "@" + hostAddr;
      const guide = [
        "[" + btn.dataset.lab + "] " + t("GPU 서버 접속 안내"),
        "- " + t("사용자") + ": " + btn.dataset.user,
        "- " + t("접속 명령") + ": " + cmd,
        "- " + t("개인 폴더") + ": /home/" + btn.dataset.user,
      ].join("\n");
      window.orviaCopy?.(guide, "접속 안내 문구를 복사했습니다.");
    });
  });

  if (location.hash && location.hash.startsWith("#account-")) {
    const name = decodeURIComponent(location.hash.slice("#account-".length));
    focusAccount(name, true);
  } else if (cards.length) {
    focusAccount(cards[0].dataset.accountName, false);
  }
})();
