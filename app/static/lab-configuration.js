(() => {
  const root = document.querySelector('.lab-configuration');
  if (!root || root.dataset.section === 'overview') return;
  const original = JSON.parse(root.dataset.gpus).map(String).sort((a,b)=>Number(a)-Number(b));
  const capacity = Number(root.dataset.storage);
  const gpuInputs = [...document.querySelectorAll('input[name="gpu_selection"]')];
  const storageInput = document.querySelector('input[name="size_gb"]');
  const form = (gpuInputs[0] || storageInput)?.form;
  if (!form) return;
  const trText = s => typeof tr === 'function' ? tr(s) : s;
  function chip(text, kind='') { const e=document.createElement('span');e.textContent=text;e.className=kind;return e; }
  function render() {
    const selected = gpuInputs.length ? gpuInputs.filter(i=>i.checked).map(i=>i.value).sort((a,b)=>Number(a)-Number(b)) : original;
    const added=selected.filter(x=>!original.includes(x)), removed=original.filter(x=>!selected.includes(x));
    const amount=storageInput ? Number(storageInput.value) : capacity;
    const valid=storageInput ? storageInput.value !== '' && storageInput.validity.valid : selected.length > 0;
    root.querySelector('[data-proposed-gpus]').replaceChildren(...(selected.length ? selected.map(x=>chip('GPU '+x,added.includes(x)?'added':'')) : [chip(trText('GPU 선택 필요'),'removed')]));
    root.querySelector('[data-proposed-storage]').textContent = Number.isFinite(amount) && amount>0 ? amount.toLocaleString()+' GB' : '—';
    const items = [...added.map(x=>chip('+ GPU '+x,'added')),...removed.map(x=>chip('− GPU '+x,'removed'))];
    if (storageInput && Number.isFinite(amount) && amount!==capacity) items.push(chip((amount>capacity?'+':'')+(amount-capacity).toLocaleString()+' GB',amount>capacity?'added':'removed'));
    root.querySelector('[data-change-items]').replaceChildren(...items);
    root.querySelector('[data-change-status]').textContent = trText(!valid ? '입력값 확인 필요' : !items.length ? '변경 없음' : gpuInputs.length ? '환경 재생성 · 실행 작업 중단' : '저장공간 확장 · 재시작 없음');
    root.classList.toggle('has-changes',items.length>0);
  }
  form.addEventListener('input',render);form.addEventListener('change',render);
  root.querySelector('[data-reset-comparison]').onclick=()=>{form.reset();render();};
  render();
})();
