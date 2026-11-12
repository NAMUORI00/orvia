(() => {
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
