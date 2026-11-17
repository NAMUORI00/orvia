(() => {
  const t = (s) => (typeof tr === "function" ? tr(String(s)) : String(s));
  const search = document.querySelector("[data-account-search]");
  const cards = [...document.querySelectorAll("[data-account-card]")];
  const grid = document.querySelector(".account-card-grid");
  const hostAddr = grid?.dataset.accessHost || document.querySelector("[data-access-host]")?.dataset.accessHost || location.hostname;

  search?.addEventListener("input", () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      card.hidden = !card.dataset.search.toLocaleLowerCase().includes(query);
      if (!card.hidden) visible++;
    });
    const empty = document.querySelector("[data-account-empty]");
    if (empty) empty.hidden = visible > 0;
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
    const target = document.getElementById(location.hash.slice(1));
    if (target && target.matches("details")) {
      target.open = true;
      target.scrollIntoView({ block: "center" });
    }
  }
})();
