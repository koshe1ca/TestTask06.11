'use strict';

const $ = id => document.getElementById(id);
const state = {files: [], analysis: null, chosen: null, sourceId: null, focus: null, mode: null};
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindRu = {contract:'Основной договор',addendum:'Допсоглашение',letter:'Письмо',draft:'Неподписанный проект',unknown:'Неопределённый тип'};
const value = condition => condition?.display ?? 'нет данных';

function toast(message, isError=true) {
  const node = $('toast'); node.textContent = message; node.hidden = !message;
  node.style.background = isError ? '#fff2e8' : '#e8f8ee';
  node.style.color = isError ? '#955b35' : '#21694e';
  if (message) window.scrollTo({top: 0, behavior: 'smooth'});
}

function sourceLink(e, text='К источнику ↗') {
  if (!e) return '';
  return `<button type="button" class="source-button" data-source="${h(e.source_id)}" data-paragraph="${Number(e.paragraph)}">${h(text)}</button>`;
}

function evidenceCard(e) {
  if (!e) return '<div class="alert">Нет данных: подтвержденная цитата отсутствует.</div>';
  return `<div class="evidence"><p class="evidence-quote">“${h(e.quote)}”</p><div class="evidence-footer"><span class="evidence-file">▤ ${h(e.filename)} · абз. ${e.paragraph}</span>${sourceLink(e)}</div></div>`;
}

function alerts(list) {
  return (list || []).map(item => `<div class="alert">⚠ ${h(item)}</div>`).join('');
}

function renderFiles() {
  $('fileCount').textContent = String(state.files.length);
  $('fileList').innerHTML = state.files.length
    ? state.files.map(f => `<div class="file-list-item"><span>▤</span><b>${h(f.name)}</b></div>`).join('')
    : '<p class="muted small">Файлы пока не выбраны.</p>';
}

async function analyseFiles() {
  if (!state.files.length) {state.analysis=null;renderAll();return;}
  const date = $('checkDate').value;
  if (!date) {toast('Укажите дату проверки.');return;}
  const btn = $('downloadCsv'); btn.disabled = true;
  $('modeLabel').textContent='Проверка документов…';
  try {
    const res = await fetch('/api/analyse', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({files:state.files,as_of:date})
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || 'Не удалось выполнить анализ.');
    state.analysis=result;
    state.chosen = result.contracts.some(c=>c.id===state.chosen) ? state.chosen : result.contracts[0]?.id;
    state.sourceId = result.sources.some(s=>s.source_id===state.sourceId) ? state.sourceId : result.sources[0]?.source_id;
    state.focus=null;
    toast('');
    renderAll();
  } catch(err) {
    state.analysis=null;
    renderAll();
    toast(err.message || String(err));
  }
}

async function loadDemo() {
  try {
    const res = await fetch('/api/demo');
    if (!res.ok) throw new Error('Не удалось загрузить демонстрационные документы.');
    state.files=(await res.json()).files;
    state.mode='Исходные учебные документы';
    state.chosen=null;state.sourceId=null;
    $('fileInput').value='';
    renderFiles();
    await analyseFiles();
  } catch(err){toast(err.message);}
}

async function handleUpload(event) {
  const files=Array.from(event.target.files || []);
  if (!files.length) return;
  if (files.length>30) return toast('Не более 30 TXT-файлов за раз.');
  if (files.some(f=>f.size>2097152)) return toast('Размер каждого файла не должен превышать 2 МБ.');
  if (files.some(f=>!f.name.toLowerCase().endsWith('.txt'))) return toast('Поддерживаются только файлы TXT.');
  try {
    state.files = await Promise.all(files.map(async f=>{
      const bytes=new Uint8Array(await f.arrayBuffer());
      let text;
      if (bytes[0]===0xff && bytes[1]===0xfe) text=new TextDecoder('utf-16le').decode(bytes);
      else if(bytes[0]===0xfe && bytes[1]===0xff) text=new TextDecoder('utf-16be').decode(bytes);
      else {
        try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}
        catch{ text=new TextDecoder('windows-1251').decode(bytes); }
      }
      return {name:f.name, text};
    }));
    state.mode='Загруженные TXT';state.chosen=null;state.sourceId=null;
    renderFiles();
    await analyseFiles();
  } catch(err){toast('Ошибка чтения TXT: '+err.message);}
}

function activateTab(tab) {
  document.querySelectorAll('.tab').forEach(node=>{
    const selected = node.dataset.tab===tab;
    node.classList.toggle('active',selected);
    node.setAttribute('aria-selected',String(selected));
  });
  document.querySelectorAll('.tab-content').forEach(node=>node.classList.toggle('active',node.id===tab));
}

function renderAll() {
  const a=state.analysis;
  $('workspace').hidden=!a; $('emptyState').hidden=!!a;
  $('downloadCsv').disabled=!a;
  $('modeLabel').textContent= a ? state.mode || 'Загружено' : 'Нет данных';
  if (!a) return;
  $('metricContracts').textContent=a.contracts.length;
  $('metricApplied').textContent=a.contracts.reduce((n,c)=>n+c.applied.length,0);
  $('metricNotices').textContent=a.contracts.reduce((n,c)=>n+c.notices.length,0);
  $('metricReview').textContent=a.contracts.filter(c=>c.needs_review).length+a.unmatched.length;
  $('asOfLabel').textContent=a.as_of;
  renderTable();renderDetails();renderQuestions();renderSourcesSelect();renderSource();renderDiagnostics();
}

function contractStatus(c) {
  if(c.needs_review) return '<span class="status review">! Нужна проверка</span>';
  if(c.notices.length) return '<span class="status notice">◉ Есть предложения</span>';
  return '<span class="status ok">✓ Проверено</span>';
}

function renderTable() {
  const a=state.analysis; if(!a) return;
  const q=$('filterInput').value.trim().toLowerCase();
  const filtered=a.contracts.filter(c=>`${c.id} ${c.supplier}`.toLowerCase().includes(q));
  $('contractsTable').innerHTML= filtered.length ? filtered.map(c=>
    `<tr data-contract="${h(c.id)}" class="${c.id===state.chosen?'selected':''}" tabindex="0" role="button" aria-label="Показать договор ${h(c.id)}">
    <td class="contract-id">${h(c.id)}</td><td class="supplier">${h(c.supplier)}</td><td class="amount">${h(value(c.amount))}</td>
    <td class="dateval">${h(value(c.deadline))}</td><td>${contractStatus(c)}</td><td class="row-arrow">›</td></tr>`
  ).join('') : '<tr><td colspan="6" class="muted">Нет договоров по запросу или основные договоры не распознаны.</td></tr>';
}

function conditionCard(label, condition, valueClass, extra='', fallbackEvidence=null) {
  return `<div class="field-card"><span class="field-name">${h(label)}</span><div class="field-value ${valueClass||''}">${h(value(condition))}</div>${extra}${evidenceCard(condition?.evidence || fallbackEvidence)}</div>`;
}

function renderDetails() {
  const c=state.analysis?.contracts.find(c=>c.id===state.chosen);
  if(!c) {$('selectedContractHeading').textContent='Договор не выбран';$('contractDetails').innerHTML='';return;}
  $('selectedContractHeading').textContent=c.id;
  const applied=c.applied.length ? `<div class="applied">✓ Учтено подписанное соглашение: ${c.applied.map(s=>h(s.filename)+' (с '+h(s.effective_date)+')').join('; ')}</div>` : '';
  const notices=c.notices.length ? `<div class="notice-section"><h3>Неприменённые изменения / предложения (${c.notices.length})</h3>${c.notices.map(n=>
    `<div class="notice-card"><div class="notice-title">▤ ${h(n.filename)}</div><div class="notice-reason">${h(n.reason)}</div>
    ${n.deadline?`<div class="notice-line">Предложенный / указанный срок: <b>${h(value(n.deadline))}</b> · не применён</div>${evidenceCard(n.deadline.evidence)}`:''}
    ${n.amount?`<div class="notice-line">Предложенная / указанная сумма: <b>${h(value(n.amount))}</b> · не применена</div>${evidenceCard(n.amount.evidence)}`:''}</div>`
  ).join('')}</div>` : '';
  $('contractDetails').innerHTML=`<div class="detail-grid">
    <div class="field-card wide"><span class="field-name">Поставщик</span><div class="field-value supplier-value">${h(c.supplier)}</div>${evidenceCard(c.supplier_evidence)}</div>
    ${conditionCard('Сумма договора',c.amount,'','',c.missing_amount_evidence)}
    ${conditionCard('Срок поставки',c.deadline,'')}
  </div>${applied}${notices}${alerts(c.issues)}`;
}

function renderQuestions() {
  const a=state.analysis; if(!a) return;
  const questions=[
    `Какой срок поставки действует по договору STN-101 на ${a.as_of}?`,
    'Какова сумма договора STN-102?',
    'Какова сумма договора STN-103?',
    'По каким договорам поставка запланирована раньше 1 апреля 2026 года и есть ли несогласованные изменения срока?'
  ];
  $('answers').innerHTML=`<div class="answers-list">${a.answers.map((ans,i)=>
    `<article class="answer-card"><div class="answer-head"><span class="question-number">0${i+1}</span><div><h3 class="question-title">${h(questions[i])}</h3><p class="answer-text">${h(ans.text)}</p></div></div>
    ${ans.evidence.length ? `<div class="answer-evidence"><div class="answer-sources-title">ПОДТВЕРЖДАЮЩИЕ ИСТОЧНИКИ (${ans.evidence.length})</div>${ans.evidence.map(evidenceCard).join('')}</div>` : '<div class="alert">Подтвержденная цитата отсутствует.</div>'}
    ${alerts(ans.caveats)}</article>`
  ).join('')}</div>`;
}

function renderSourcesSelect() {
  const a=state.analysis; if(!a) return;
  $('sourceSelect').innerHTML=a.sources.map(s=>`<option value="${h(s.source_id)}">${h(s.filename)}</option>`).join('');
  $('sourceSelect').value=state.sourceId;
}

function renderSource() {
  const src=state.analysis?.sources.find(s=>s.source_id===state.sourceId);
  if(!src){$('sourceParagraphs').innerHTML='<div class="alert">Нет выбранного документа.</div>';return;}
  $('sourceMeta').innerHTML=`<b>${h(kindRu[src.kind])}</b> · привязка: ${h(src.contract_ids.join(', ')||'нет данных')}${src.effective_date?' · вступает в силу: '+h(src.effective_date):''} · ${src.paragraphs.length} абз.`;
  $('sourceParagraphs').innerHTML=src.paragraphs.map((p,i)=>{
    const focus=state.focus && state.focus.source_id===src.source_id && state.focus.paragraph===i+1;
    return `<div id="paragraph-${i+1}" class="para ${focus?'focus':''}"><div class="para-num">АБЗАЦ ${i+1}</div><div class="para-text">${h(p)}</div></div>`;
  }).join('');
  if(state.focus && state.focus.source_id===src.source_id){
    const node=$(`paragraph-${state.focus.paragraph}`);
    if(node) node.scrollIntoView({behavior:'smooth',block:'center'});
  }
}

function openEvidence(sourceId, paragraph) {
  state.sourceId=sourceId;state.focus={source_id:sourceId,paragraph:Number(paragraph)};
  activateTab('sources');
  renderSourcesSelect();renderSource();
}

function renderDiagnostics() {
  const a=state.analysis;if(!a)return;
  $('diagnosticsItems').innerHTML=`${a.sources.map(s=>
    `<div class="diagnostic-card"><h3>▤ ${h(s.filename)}</h3><div class="diagnostic-meta">
      Тип: <strong>${h(kindRu[s.kind])}</strong> · договор: <strong>${h(s.contract_ids.join(', ')||'нет данных')}</strong><br>
      Сумма: <strong>${h(value(s.amount))}</strong> · срок: <strong>${h(value(s.deadline))}</strong>
      ${s.kind==='addendum'?`<br>Подписи: <strong>${s.signed===true?'подтверждены':'не подтверждены'}</strong> · вступает в силу: <strong>${h(s.effective_date||'нет данных')}</strong>`:''}
      </div>${alerts(s.issues)}</div>`
  ).join('')}${a.unmatched.length?`<div class="alert error">Непривязанные документы: ${h(a.unmatched.map(s=>s.filename).join(', '))}.</div>`:''}${alerts(a.global_issues)}
  <div class="alert">Правила и шаблоны не гарантируют извлечения свободного юридического текста. При отсутствии суммы, срока, однозначной связи или даты вступления в силу требуется проверка специалистом.</div>`;
}

function csvExport() {
  if(!state.analysis)return;
  const records=[['Договор','Поставщик','Сумма, руб.','Срок поставки','Источник суммы','Источник срока','Предложения','Проверка']];
  for(const c of state.analysis.contracts)records.push([
    c.id,c.supplier,c.amount?.value||'нет данных',value(c.deadline),
    c.amount?.evidence?.filename||'нет данных',c.deadline?.evidence?.filename||'нет данных',
    c.notices.length,c.needs_review?'Да':'Нет']);
  const csv='\uFEFF'+records.map(row=>row.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(';')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='textnavigator-summary.csv';a.click();URL.revokeObjectURL(url);
}

$('fileInput').addEventListener('change',handleUpload);
$('loadDemo').addEventListener('click',loadDemo);
$('demoCta').addEventListener('click',loadDemo);
$('clearAll').addEventListener('click',()=>{
  state.files=[];state.analysis=null;state.mode=null;state.focus=null;
  $('fileInput').value='';toast('');renderFiles();renderAll();
});
$('checkDate').addEventListener('change',()=>state.files.length && analyseFiles());
$('filterInput').addEventListener('input',renderTable);
$('downloadCsv').addEventListener('click',csvExport);
$('sourceSelect').addEventListener('change',e=>{state.sourceId=e.target.value;state.focus=null;renderSource();});
document.addEventListener('click',e=>{
  const button=e.target.closest('button[data-source]');
  if(button){openEvidence(button.dataset.source,button.dataset.paragraph);return;}
  const row=e.target.closest('tr[data-contract]');
  if(row){state.chosen=row.dataset.contract;renderTable();renderDetails();}
  const tab=e.target.closest('.tab');
  if(tab)activateTab(tab.dataset.tab);
});
document.addEventListener('keydown',e=>{
  if((e.key==='Enter'||e.key===' ') && e.target.matches('tr[data-contract]')){
    e.preventDefault();state.chosen=e.target.dataset.contract;renderTable();renderDetails();
  }
});
renderFiles();renderAll();
