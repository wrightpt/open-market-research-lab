const $ = (selector) => document.querySelector(selector);
const state = {session: null, meta: null, studies: [], current: null, parent: null, draft: null};
const pending = new Map();
const labels = {draft: 'Draft', submitted: 'Awaiting replay', reproduced: 'Replay matched', disputed: 'Disputed', failed: 'Failed attempt', running: 'Running', verifying: 'Replaying'};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function append(parent, ...children) { parent.append(...children.filter(Boolean)); return parent; }
function link(text, href, className) {
  const node = el('a', text, className); node.href = href; return node;
}
function button(text, action, className = 'button') {
  const node = el('button', text, className); node.type = 'button';
  node.addEventListener('click', () => perform(node, action)); return node;
}
function badge(status) { return el('span', labels[status] || status.replaceAll('_', ' '), `badge ${status}`); }
function number(value, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('en-US', {maximumFractionDigits: digits, minimumFractionDigits: digits}) : 'Unavailable';
}
function percentage(value) { return typeof value === 'number' && Number.isFinite(value) ? `${number(value * 100)}%` : 'Unavailable'; }
function date(value) { return new Date(value).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'}); }
function notice(message, error = false) {
  const node = $('#notice'); node.textContent = message; node.className = error ? 'error' : ''; node.hidden = false;
}
async function perform(node, action) {
  node.disabled = true;
  try { await action(); }
  catch (error) { notice(error.message, true); }
  finally { node.disabled = false; }
}
async function api(path, body) {
  const options = {credentials: 'same-origin', redirect: 'error', headers: {}};
  let requestId;
  if (body !== undefined) {
    const serialized = JSON.stringify(body);
    requestId = `${state.session.actor}:${path}:${serialized}`;
    if (!pending.has(requestId)) pending.set(requestId, crypto.randomUUID());
    Object.assign(options, {method: 'POST', body: serialized});
    options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': state.session.csrf_token,
      'Idempotency-Key': pending.get(requestId)};
  }
  let response;
  try { response = await fetch(`/commons/api/${path}`, options); }
  catch { throw new Error('Cannot reach the local server. Check the register before retrying; evidence may already be saved.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `Request failed (${response.status}).`);
  if (requestId) pending.delete(requestId);
  return data;
}
async function refresh() {
  const result = await api('studies'); state.studies = result.studies; renderRegister();
}

function renderRegister() {
  const counts = [['Studies retained', state.studies.length], ['Awaiting replay', state.studies.filter(s => s.status === 'submitted').length],
    ['Replays matched', state.studies.filter(s => s.status === 'reproduced').length], ['Disputed reports', state.studies.filter(s => s.status === 'disputed').length]];
  $('#stats').replaceChildren(...counts.map(([label, count]) => append(el('div', null, 'stat'), el('strong', count.toString().padStart(2, '0')), el('span', label))));
  const query = $('#search').value.toLowerCase().trim(), filter = $('#filter').value;
  const matches = state.studies.filter(s => (filter === 'all' || s.status === filter) &&
    `${s.submission.title} ${s.submission.hypothesis} ${s.submission.strategy.name}`.toLowerCase().includes(query));
  const rows = matches.map((study, i) => {
    const row = el('article', null, 'study-row'), content = el('div'), sub = study.submission;
    append(content, append(el('h3'), link(sub.title, `#study/${study.id}`)), el('p', sub.hypothesis),
      append(el('div', null, 'row-meta'), el('span', 'SYNTHETIC · DEVELOPMENT'), el('span', date(study.created_at)), el('span', study.parent_id ? 'LINKED REVISION' : 'ORIGINAL STUDY')));
    const arrow = link('↗', `#study/${study.id}`, 'row-arrow'); arrow.setAttribute('aria-label', `Open ${sub.title}`);
    return append(row, el('span', `${i + 1}`.padStart(2, '0'), 'row-number'), content,
      append(el('div', null, 'row-end'), badge(study.status), arrow));
  });
  $('#study-list').replaceChildren(...(rows.length ? rows : [el('p', state.studies.length ? 'No studies match this search. Try another phrase or status.' : 'Your first question starts the register. Create a study to begin.', 'empty-state')]));
  $('#result-count').textContent = `${matches.length} OF ${state.studies.length} STUDIES`;
}
function facts(pairs) {
  return append(el('dl', null, 'facts'), ...pairs.map(([name, value, isHash]) =>
    append(el('div'), el('dt', name), el('dd', value, isHash ? 'hash' : ''))));
}
function renderDataset() {
  const d = state.meta.dataset;
  $('#dataset-facts').replaceChildren(...facts([
    ['Identity', d.id], ['Instrument', typeof d.instrument === 'object' ? JSON.stringify(d.instrument) : d.instrument],
    ['Development observations', d.development.rows], ['Coverage', `${d.development.first_close} → ${d.development.last_close}`],
    ['Time basis', d.time_basis], ['License', d.license], ['Dataset SHA-256', d.development.sha256, true], ['Engine SHA-256', d.source_sha256, true],
  ]).children);
}

function prepareForm(study = null) {
  state.parent = study?.id || null;
  state.draft = structuredClone(study?.submission || state.meta.baseline);
  state.draft.submission_id = `study-${crypto.randomUUID()}`;
  const s = state.draft, p = s.strategy.parameters;
  const values = {'study-title': study ? `${s.title.slice(0, 108)} · revision` : '', hypothesis: s.hypothesis,
    criteria: s.research.acceptance_criteria, limitations: s.research.limitations,
    lookback: p.lookback_bars, spread: p.spread_ratio_min, depth: p.depth_ratio_max,
    oi: p.oi_drop_min, signals: p.min_signals, fee: s.execution.fee_bps,
    slippage: s.execution.slippage_bps, trials: study ? Math.min(10000, s.research.development_trials + 1) : 1};
  for (const [id, value] of Object.entries(values)) $(`#${id}`).value = value;
  $('#form-title').textContent = study ? 'Let the question evolve.' : 'Open a new study.';
  $('#parent-note').textContent = study ? `Linked to ${study.submission.title}. The original stays intact.` : 'Saved studies are immutable. Fork a study to revise it.';
}

$('#study-form').addEventListener('submit', event => {
  event.preventDefault();
  const submit = event.submitter;
  perform(submit, async () => {
    const s = structuredClone(state.draft), n = id => Number($(`#${id}`).value);
    s.title = $('#study-title').value.trim(); s.hypothesis = $('#hypothesis').value.trim();
    Object.assign(s.research, {acceptance_criteria: $('#criteria').value.trim(), limitations: $('#limitations').value.trim(), development_trials: n('trials')});
    if (state.parent) s.research.prior_work = `Linked revision of Commons study ${state.parent}; prior evidence remains retained.`;
    Object.assign(s.strategy.parameters, {lookback_bars: n('lookback'), spread_ratio_min: n('spread'), depth_ratio_max: n('depth'), oi_drop_min: n('oi'), min_signals: n('signals')});
    Object.assign(s.execution, {fee_bps: n('fee'), slippage_bps: n('slippage')});
    const study = await api('studies', {submission: s, parent_id: state.parent});
    await refresh(); location.hash = `study/${study.id}`;
    notice('Study saved. The claim and method are now retained as an immutable record.');
  });
});

function history(study) {
  const trail = el('div', null, 'trail');
  const parts = [
    ['01 / CLAIM', 'Recorded', 'complete'],
    ['02 / EVIDENCE', study.evidence ? 'Report retained' : 'Not submitted', study.evidence ? 'complete' : ''],
    ['03 / REPLAY', study.reproduction ? (study.reproduction.matched ? 'Complete match' : 'Mismatch retained') : 'Not replayed', study.reproduction ? (study.reproduction.matched ? 'complete' : 'issue') : ''],
    ['04 / REVIEW', study.reviews.length ? `${study.reviews.length} decision${study.reviews.length === 1 ? '' : 's'} recorded` : 'Not reviewed', study.reviews.length ? 'complete' : ''],
  ];
  for (const [title, text, cls] of parts) append(trail, append(el('div', null, cls), el('small', title), el('span', text)));
  return trail;
}

function chart(report) {
  const values = report.equity_curve.filter(p => p && typeof p.equity === 'number' && Number.isFinite(p.equity)).map(p => p.equity);
  if (values.length < 2) return el('p', 'Equity curve unavailable.', 'muted');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 760 160'); svg.setAttribute('class', 'chart'); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Equity across the synthetic development fixture; not real-market performance');
  for (const y of [20, 80, 140]) {
    const line = document.createElementNS(svg.namespaceURI, 'line');
    for (const [k, v] of Object.entries({x1: 0, x2: 760, y1: y, y2: y})) line.setAttribute(k, v);
    svg.append(line);
  }
  const low = Math.min(...values), high = Math.max(...values), range = high - low || 1;
  if (!Number.isFinite(range)) return el('p', 'Submitted curve is outside display bounds; inspect the replay.', 'muted');
  const polyline = document.createElementNS(svg.namespaceURI, 'polyline');
  polyline.setAttribute('points', values.map((v, i) => `${(i / (values.length - 1) * 760).toFixed(2)},${(140 - ((v - low) / range) * 120).toFixed(2)}`).join(' '));
  svg.append(polyline); return svg;
}

function results(study) {
  if (!study.evidence) return append(el('div', null, 'boundary'), el('h3', 'The evidence is still to come.'), el('p', 'Run the development experiment or attach a complete benchmark report. The saved claim will stay unchanged.'));
  const claimed = study.evidence.report, replayed = study.reproduction?.report;
  const panel = el('section', null, 'result-panel');
  append(panel, el('p', study.reproduction?.matched ? 'EXACT REPORT MATCH · SYNTHETIC DEVELOPMENT' : 'SUBMITTED VALUES · CHECK AGAINST REPLAY', 'eyebrow'), el('h2', 'The result, in full context.'));
  if (study.reproduction && !study.reproduction.matched) {
    append(panel, append(el('div', null, 'boundary'), el('h3', 'This report did not reproduce.'), el('p', `Differing sections: ${study.reproduction.differing_sections.join(', ')}. Both reports remain in the evidence package.`)));
  }
  const table = el('table'), head = el('tr');
  ['Metric', 'Submitted', 'Replay', 'Always long¹', 'Always cash¹'].forEach(t => head.append(el('th', t)));
  table.append(append(el('thead'), head)); const body = el('tbody');
  for (const [name, key, formatter] of [['Net return', 'net_return_fraction', percentage], ['Max close drawdown', 'max_close_drawdown_fraction', percentage], ['Fees paid', 'fees_paid', number], ['Adverse slippage cost', 'slippage_cost', number], ['Fills', 'fills', v => number(v, 0)]]) {
    const control = replayed || claimed;
    const row = el('tr');
    append(row, el('td', name), el('td', formatter(claimed.summary[key])), el('td', replayed ? formatter(replayed.summary[key]) : 'Not replayed'), el('td', formatter(control.controls.always_long_after_warmup[key])), el('td', formatter(control.controls.always_cash[key])));
    body.append(row);
  }
  table.append(body); append(panel, append(el('div', null, 'table-scroll'), table));
  append(panel, el('p', `¹ Controls from ${replayed ? 'the fresh replay' : 'the submitted report; not yet verified'}. Same costs and warmup. Return is a fixture calculation, not a market forecast.`, 'fineprint'));
  append(panel, chart(replayed || claimed), el('p', `${replayed ? 'REPLAY' : 'SUBMITTED'} EQUITY · 384 SYNTHETIC BARS · RESCALED VERTICAL AXIS`, 'chart-caption'));
  const disclosure = el('details');
  append(disclosure, el('summary', 'Inspect report identities'), facts([
    ['Submission SHA-256', claimed.provenance.submission_sha256, true], ['Submitted report SHA-256', study.evidence.sha256, true],
    ['Replay SHA-256', study.reproduction?.sha256 || 'Not replayed', true], ['Evidence source', study.evidence.origin],
  ])); panel.append(disclosure);
  return panel;
}

async function mutateStudy(action, body = {}) {
  const id = state.current.id;
  const study = await api(`studies/${id}/${action}`, body);
  await refresh();
  if (location.hash === `#study/${id}`) renderStudy(study);
  if (study.status === 'failed') notice('The attempt failed and was retained. Inspect its history before retrying.', true);
  else notice(action === 'reproduce' ? (study.reproduction.matched ? 'Complete report matched the fresh replay.' : 'Replay found differences. Both reports have been retained.') : 'Evidence saved to the local journal.');
}

function reviewSection(study) {
  const section = el('section'), heading = append(el('div', null, 'section-heading'), el('h2', 'Review & disagreement'), el('span', `${study.reviews.length} DECISIONS`, 'eyebrow'));
  section.append(heading);
  if (!study.reviews.length) section.append(el('p', 'No reviewer decision has been recorded.', 'muted'));
  for (const review of study.reviews) {
    const item = el('article', null, 'review');
    append(item, append(el('div', null, 'actions'), badge(review.verdict), el('small', `${state.meta.personas[review.actor]} · ${date(review.at)}`)), el('p', review.rationale), el('small', `Conflicts / independence: ${review.conflicts}`));
    section.append(item);
  }
  if (state.session.actor !== study.author && study.reproduction) {
    const form = el('form', null, 'paper'); form.id = 'review-form';
    append(form, el('h3', 'Add a reviewer decision'), el('p', 'A review is an opinion about this engineering record. It does not grant a scientific-validity badge.', 'muted'));
    const verdict = el('select'); verdict.id = 'verdict'; verdict.name = 'verdict';
    for (const [value, title] of [['accepted', 'Accept engineering record'], ['needs_changes', 'Request a revision'], ['rejected', 'Reject this evidence']]) {
      const option = el('option', title); option.value = value;
      if (value === 'accepted' && !study.reproduction.matched) option.disabled = true;
      verdict.append(option);
    }
    if (!study.reproduction.matched) verdict.value = 'needs_changes';
    const verdictLabel = el('label', 'Decision'); verdictLabel.htmlFor = 'verdict'; append(form, verdictLabel, verdict);
    for (const [id, title, minimum, maximum] of [['rationale', 'Reasoning', 20, 2000], ['conflicts', 'Conflicts and independence disclosure', 5, 500]]) {
      const label = el('label', title); label.htmlFor = id;
      const input = el('textarea'); input.id = id; input.name = id; input.required = true; input.minLength = minimum; input.maxLength = maximum; input.rows = id === 'rationale' ? 3 : 2;
      if (id === 'conflicts') input.value = 'Same local operator using a demo reviewer persona; not independent human review.';
      append(form, label, input);
    }
    const submit = el('button', 'Record review →', 'button primary'); submit.type = 'submit'; form.append(submit);
    form.addEventListener('submit', event => {
      event.preventDefault(); perform(submit, () => mutateStudy('review', {verdict: verdict.value, rationale: $('#rationale').value, conflicts: $('#conflicts').value}));
    }); section.append(form);
  }
  return section;
}

function renderStudy(study) {
  state.current = study;
  const s = study.submission, author = study.author === state.session.actor;
  const container = $('#study-detail'); container.replaceChildren();
  append(container, link('← Research register', '#studies', 'back-link'));
  const heading = el('div', null, 'study-heading');
  append(heading, badge(study.status), el('h1', s.title), append(el('div', null, 'row-meta'), el('span', state.meta.personas[study.author]), el('span', date(study.created_at)), el('span', 'SYNTHETIC · DEVELOPMENT')));
  const actions = el('div', null, 'actions');
  if (author && !study.evidence) {
    actions.append(button('Run development experiment →', () => mutateStudy('run'), 'button primary'));
    const upload = el('label', 'Attach report', 'button upload-label'), file = el('input'); file.type = 'file'; file.accept = '.json,application/json'; file.setAttribute('aria-label', 'Attach benchmark report'); upload.append(file);
    file.addEventListener('change', async () => {
      if (!file.files.length) return;
      await perform(file, async () => {
        if (file.files[0].size > state.meta.limits.report_bytes) throw new Error('The report exceeds the 2 MB import limit.');
        const parsed = JSON.parse(await file.files[0].text());
        const report = parsed.kind === 'commons_evidence_package' ? parsed.study?.evidence?.report : parsed;
        await mutateStudy('import', {report});
      }); file.value = '';
    }); actions.append(upload);
  }
  if (!author && study.evidence && !study.reproduction) actions.append(button('Replay & compare →', () => mutateStudy('reproduce'), 'button primary'));
  actions.append(button('Fork a revision ↗', async () => { prepareForm(study); location.hash = `new/${study.id}`; }));
  actions.append(link('Download submission ↓', `/commons/api/studies/${study.id}/submission`, 'button small'));
  if (study.evidence) actions.append(link('Export evidence ↓', `/commons/api/studies/${study.id}/export`, 'button small'));
  append(heading, actions);
  if (author && study.evidence && !study.reproduction) heading.append(el('p', 'Switch to Local reviewer in the sidebar to exercise the replay and review workflow.', 'fineprint'));
  if (!author && !study.evidence) heading.append(el('p', 'The author persona can run or attach the first report.', 'fineprint'));
  if (study.parent_id) heading.append(append(el('p', null, 'fineprint'), link('↖ Open the parent study', `#study/${study.parent_id}`)));
  append(container, heading, history(study));
  const claim = el('article', null, 'paper');
  append(claim, el('p', 'THE RECORDED CLAIM', 'eyebrow'), el('h3', 'Hypothesis'), el('p', s.hypothesis), el('h3', 'Acceptance & rejection'), el('p', s.research.acceptance_criteria), el('h3', 'Limitations'), el('p', s.research.limitations));
  const method = el('aside', null, 'note-card');
  append(method, el('p', 'THE METHOD', 'eyebrow'), el('h3', 'A bounded experiment.'), facts([
    ['Fixture', s.dataset.id], ['Lookback / required signals', `${s.strategy.parameters.lookback_bars} bars / ${s.strategy.parameters.min_signals}`],
    ['Fee / adverse slippage', `${s.execution.fee_bps} / ${s.execution.slippage_bps} bps per fill`], ['Timing', 'Decision at close → fill at next open'],
    ['Trials disclosed', s.research.development_trials], ['Engine fingerprint', study.source_sha256, true],
  ]));
  const config = el('details'); append(config, el('summary', 'Full saved submission'), el('pre', JSON.stringify(s, null, 2))); method.append(config);
  append(container, append(el('div', null, 'study-layout'), claim, method), results(study), reviewSection(study));
  if (study.attempts.length) {
    const attempts = el('details'); append(attempts, el('summary', `Retained attempt history (${study.attempts.length})`));
    for (const item of study.attempts) attempts.append(el('p', `${date(item.at)} · ${item.kind.replaceAll('_', ' ')} · ${item.status}${item.message ? ` — ${item.message}` : ''}`, 'fineprint'));
    container.append(attempts);
  }
}

let routeSequence = 0;
async function route() {
  if (!state.meta) return;
  const sequence = ++routeSequence;
  const [view = 'studies', id] = location.hash.slice(1).split('/');
  const valid = ['studies', 'study', 'new', 'dataset', 'guide'].includes(view) ? view : 'studies';
  if (valid === 'new') {
    if (id && !/^[a-f0-9]{16}$/.test(id)) throw new Error('That parent study link is invalid. Open the research register.');
    if (id) { const parent = await api(`studies/${id}`); if (sequence !== routeSequence) return; prepareForm(parent); }
    else prepareForm();
  }
  if (valid === 'study') {
    if (!/^[a-f0-9]{16}$/.test(id || '')) throw new Error('That study link is invalid. Open the research register.');
    const study = await api(`studies/${id}`); if (sequence !== routeSequence) return; renderStudy(study);
  }
  if (valid === 'studies') await refresh();
  if (sequence !== routeSequence) return;
  for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== `${valid}-view`;
  const names = {studies: 'RESEARCH REGISTER', study: 'STUDY RECORD', new: 'NEW STUDY', dataset: 'DATASET & METHOD', guide: 'FIELD GUIDE'};
  $('#breadcrumb').textContent = names[valid];
  for (const anchor of document.querySelectorAll('[data-nav]')) {
    if (anchor.dataset.nav === (['new', 'study'].includes(valid) ? 'studies' : valid)) anchor.setAttribute('aria-current', 'page');
    else anchor.removeAttribute('aria-current');
  }
  document.title = `${valid === 'study' ? state.current.submission.title : 'Open Research Commons'} · Research workspace`;
  $('#main').focus({preventScroll: true}); window.scrollTo(0, 0);
}

$('#search').addEventListener('input', renderRegister);
$('#filter').addEventListener('change', renderRegister);
$('#persona').addEventListener('change', event => perform(event.target, async () => {
  const next = event.target.value;
  try {
    await api('persona', {actor: next}); state.session.actor = next;
    if (location.hash.startsWith('#study/')) await route();
    else await refresh();
  }
  catch (error) { event.target.value = state.session.actor; throw error; }
  notice(`Using ${state.meta.personas[next]}. This is a local workflow persona, not independent authentication.`);
}));
window.addEventListener('hashchange', () => route().catch(error => notice(error.message, true)));

async function start() {
  state.session = await api('session'); state.meta = await api('meta');
  $('#persona').value = state.session.actor; renderDataset(); await route();
}
start().catch(error => {
  notice(error.message, true);
  $('#study-list').replaceChildren(el('p', 'The local workspace could not be loaded. Start the server and reload this page.', 'empty-state'));
});
