// Execute the actual dashboard renderer against shared and separate samples.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.textContent=''; this.value=''; this.classList={toggle(){},remove(){}}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; this.textContent=''; }
  setAttribute() {}
  addEventListener() {}
  showModal() { this.open=true; }
  close() { this.open=false; }
  querySelectorAll() { return []; }
  querySelector() { return this.note ||= new Element(); }
  text() { return this.textContent + this.children.map(c=>typeof c==='string'?c:c.text()).join(' '); }
}
const code=fs.readFileSync(path.join(__dirname,'../app/static/monitor.js'),'utf8');
async function render({missing=false,stopped=false,english=false}={}) {
  const nodes=new Map();
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
  get('monitor-window').value='2';
  const accounts=Array.from({length:12},(_,i)=>({lab:'shared',user:'user'+i,scope:'shared_container',running:!stopped,cpu:null,memory:null,processes:[]}));
  accounts.push({lab:'separate',user:'solo',running:true,cpu:400,memory:'1GiB / 8GiB',processes:[],rates:{rx:2,tx:3}});
  const latest={ts:Date.now()/1000,accounts,shared_totals:missing?{}:{shared:{running:!stopped,cpu:250,memory:'64MiB / 8GiB',rates:{rx:1024,tx:2048}}},cpu_count:32,cpu_util:20,memory_total:8*1024**3,memory_used:1024**3,gpus:[],disks:['shared','separate'].map(lab=>({lab,title:lab,mounted:true,used:100,capacity:1000,gpu_indices:[]}))};
  const data={latest,history:[],network_usage:[],settings:{archive_days:90},events:[]};
  const messages=english?JSON.parse(fs.readFileSync(path.join(__dirname,'../app/locales/en.json'),'utf8')):{};
  const viz={svg:tag=>new Element(tag),chart(){},hint(){},hide(){},show(){}};
  const context={document:{documentElement:{lang:english?"en":"ko"},getElementById:get,createElement:tag=>new Element(tag),addEventListener(){}},window:{OrviaViz:viz},fetch:async url=>({ok:true,json:async()=>url==='/api/translations'?messages:data}),setTimeout(){},clearTimeout(){},Date};
  vm.runInNewContext(code,context);
  await new Promise(setImmediate);
  assert.equal(get('monitor-error').textContent,'');
  return {get,latest};
}
(async()=>{
  let {get}=await render();
  const cards=get('monitor-labs').children;
  assert.match(cards[0].text(),/2.5c/);
  assert.match(cards[0].text(),/67.1 MB/);
  assert.match(cards[0].text(),/1.0 KiB[/]s.*2.0 KiB[/]s/);
  assert.doesNotMatch(cards[0].text(),/30.0c/);
  assert.equal(get('monitor-users').children.length,12);
  assert.match(get('lab-users-panel').note.text(),/공용 컨테이너 전체 사용량/);
  for(const c of get('monitor-users').children) {assert.match(c.text(),/개별 집계 미지원/);assert.doesNotMatch(c.text(),/N[/]A/);}
  assert.match(get('network-ranking').text(),/개별 집계 미지원/);
  assert.doesNotMatch(get('network-ranking').text(),/N[/]A/);
  get('monitor-users').children[0].children[0].onclick();
  assert.match(get('detail-body').text(),/개별 집계 미지원/);
  assert.doesNotMatch(get('detail-body').text(),/N[/]A/);
  get('monitor-detail').close();
  cards[1].onclick();
  assert.match(get('monitor-labs').children[1].text(),/4.0c/);
  assert.match(get('monitor-labs').children[1].text(),/1G/);
  assert.doesNotMatch(get('monitor-users').text(),/개별 집계 미지원/);
  assert.match(get('lab-users-panel').note.text(),/계정 환경 기준/);
  ({get}=await render({missing:true}));
  assert.match(get('monitor-labs').children[0].text(),/N[/]A/);
  assert.match(get('monitor-users').text(),/개별 집계 미지원/);
  ({get}=await render({stopped:true}));
  assert.match(get('monitor-labs').children[0].text(),/0.0c/);
  ({get}=await render({english:true}));
  assert.match(get('monitor-users').text(),/Per-user metrics unavailable/);
  assert.match(get('monitor-labs').children[0].text(),/Shared container usage/);
  console.log('Shared totals, 12-account non-duplication, individual labels, network, separate labs, missing/stopped samples and English: passed');
})().catch(e=>{console.error(e);process.exitCode=1});
