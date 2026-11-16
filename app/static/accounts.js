(() => {
  const search = document.querySelector('[data-account-search]');
  const cards = [...document.querySelectorAll('[data-account-card]')];
  search?.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    cards.forEach(card => {
      card.hidden = !card.dataset.search.toLocaleLowerCase().includes(query);
      if (!card.hidden) visible++;
    });
    document.querySelector('[data-account-empty]').hidden = visible > 0;
  });
})();
