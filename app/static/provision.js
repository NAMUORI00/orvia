(() => {
  document.querySelectorAll('[data-storage-root]').forEach(input => {
    const preview = input.form.querySelector('[data-storage-preview]');
    input.addEventListener('input', () => {
      preview.textContent = /^[a-z][a-z0-9_-]{1,31}$/.test(input.value)
        ? input.dataset.storageRoot.replace(/\/$/, '') + '/' + input.value
        : (typeof tr === 'function' ? tr('유효한 폴더명을 입력하세요.') : '유효한 폴더명을 입력하세요.');
    });
  });
  async function update() {
    if (!document.hidden) {
      try {
        const response = await fetch('/api/provision');
        if (response.ok) {
          const data = await response.json();
          const root = document.getElementById('provision-jobs');
          root.replaceChildren(...data.jobs.map(job => {
            const line = document.createElement('p');
            line.textContent = tr(`${job.lab} · ${job.state} · ${job.message}`);
            return line;
          }));
        }
      } catch (_) { /* Keep the last visible result on transient failure. */ }
    }
    setTimeout(update, 5000);
  }
  setTimeout(update, 5000);
})();
