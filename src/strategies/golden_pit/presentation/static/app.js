(function () {
const state = {
  data: null,
  page: 'overview',
  query: '',
  selected: null,
  jobsTimer: null,
  searchTimer: null,
  overviewPollTick: 0,
  candidatePage: { page: 1, pageSize: 100, total: 0, pages: 1, facets: {stage_b: [], stage_c: []} },
  filters: { stageA: 'ALL', data: 'ALL', pe: 'ALL', dividend: 'ALL', stageB: 'ALL', stageC: 'ALL' },
  sort: { key: null, direction: 'asc' }
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const fmt = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });
const statusLabels = {
  PASS: '通过', FAIL: '未通过', SUPERSEDED: '已失效', REVIEW: '待复核', REJECT: '否决',
  COMPLETE: '数据完整', PARTIAL: '部分数据', ERROR: '数据异常', PENDING_DATA: '数据待补', DATA_ERROR: '数据异常',
  FINISHED: '已完成', FINISHED_WITH_ERRORS: '完成但有异常', RUNNING: '运行中',
  PAUSED: '已暂停', CANCELLED: '已停止', INTERRUPTED: '已中断', QUEUED: '排队中',
  SUCCEEDED: '已完成', FAILED: '失败', '未进入': '未进入',
  '待生成证据包': '待生成证据包', '待AI研究': '待 AI 研究', '待人工复核': '待人工复核', '待风险研究': '待风险研究', '已失效': '已失效'
};

function mount() {
  bindEvents();
  const now = new Date();
  const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  $('[name="as_of"]').value = localDate.toISOString().slice(0, 10);
}

function bindEvents() {
  $$('#goldenPitNav .nav-item').forEach(btn => btn.addEventListener('click', () => navigate(btn.dataset.page)));
  $$('[data-goto]').forEach(btn => btn.addEventListener('click', () => navigate(btn.dataset.goto)));
  $('#refreshButton').addEventListener('click', () => loadOverview($('#runSelect').value));
  $('#runSelect').addEventListener('change', e => loadOverview(e.target.value));
  $('#newScreenButton').addEventListener('click', () => $('#workflowModal').showModal());
  $$('.modal-close').forEach(btn => btn.addEventListener('click', () => $('#workflowModal').close()));
  $$('.review-close').forEach(btn => btn.addEventListener('click', () => $('#reviewModal').close()));
  $('#workflowForm').addEventListener('submit', startWorkflow);
  $$('[name="scope"]').forEach(input => input.addEventListener('change', updateWorkflowScope));
  $('#reviewForm').addEventListener('submit', submitReview);
  $('#candidateSearch').addEventListener('input', e => {
    state.query = e.target.value.trim().toLowerCase();
    state.candidatePage.page = 1;
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => loadCandidates(), 250);
  });
  $$('[data-filter-key]').forEach(select => select.addEventListener('change', () => {
    state.filters[select.dataset.filterKey] = select.value;
    state.candidatePage.page = 1;
    loadCandidates();
  }));
  $$('[data-sort]').forEach(button => button.addEventListener('click', () => toggleCandidateSort(button.dataset.sort)));
  $('#resetFilters').addEventListener('click', resetCandidateFilters);
  $('#candidatePrev').addEventListener('click', () => changeCandidatePage(-1));
  $('#candidateNext').addEventListener('click', () => changeCandidatePage(1));
  $('#closeDrawer').addEventListener('click', closeDrawer);
  $('#scrim').addEventListener('click', closeDrawer);
  $('#nextActionButton').addEventListener('click', nextAction);
  document.addEventListener('click', e => {
    const control = e.target.closest('[data-run-control]');
    if (control) { e.preventDefault(); e.stopPropagation(); controlRun(control.dataset.runControl, control.dataset.runId); return; }
    const recovery = e.target.closest('[data-recovery]');
    if (recovery) { e.preventDefault(); e.stopPropagation(); startRecovery(recovery.dataset.recovery, recovery.dataset.runId); return; }
    const detail = e.target.closest('[data-detail]');
    if (detail) openDrawer(detail.dataset.detail);
    const run = e.target.closest('[data-run]');
    if (run) loadOverview(run.dataset.run);
  });
  updateWorkflowScope();
}

async function loadOverview(runId = '') {
  setLoading(true);
  try {
    const params = new URLSearchParams({compact:'1'});
    if (runId) params.set('run_id', runId);
    const query = `?${params.toString()}`;
    const response = await fetch(`/api/strategies/golden-pit/overview${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '载入失败');
    state.data = data;
    if (data.run) {
      state.candidatePage.page = 1;
      await Promise.all([loadCandidates(false), loadQuality(false)]);
    }
    renderAll();
  } catch (error) { toast('数据载入失败', error.message, true); }
  finally { setLoading(false); }
}

function renderAll() {
  const d = state.data;
  renderRunSelect();
  const run = d.run;
  $('#overviewSubtitle').textContent = run ? `${run.calculation_version} · ${formatTime(run.finished_at || run.started_at)} 更新` : '尚未创建正式工作流';
  $('#asOfDate').textContent = run?.as_of_date || '—';
  $('#sourceText').textContent = d.quality.providers.length ? `${d.quality.providers.join(' · ')} · ${d.quality.gate_passed ? '质量闸门通过' : '存在阻断'}` : '等待首次运行';
  $('#candidateNavCount').textContent = d.candidate_total ?? state.candidatePage.total;
  $('#kpiUniverse').textContent = fmt.format(d.summary.universe || 0);
  $('#kpiStageA').textContent = fmt.format(d.summary.stage_a_pass || 0);
  $('#kpiReview').textContent = fmt.format(d.summary.pending_review || 0);
  $('#kpiStageC').textContent = fmt.format(d.summary.stage_c_pass || 0);
  const rate = d.summary.universe ? d.summary.stage_a_pass / d.summary.universe * 100 : 0;
  $('#kpiStageARate').textContent = `${fmt.format(rate)}% 量化初筛通过率`;
  const status = run?.status || 'EMPTY';
  $('#runStatus').textContent = statusLabels[status] || status;
  $('#runStatus').className = `status-pill ${status}`;
  populateStageFilters();
  renderPipeline(); renderOverviewCandidates(); renderCandidateTable(); renderQuality(); renderRuns();
  $('#nextActionTitle').textContent = d.next_action.title;
  $('#nextActionDetail').textContent = d.next_action.detail;
  $('#nextActionButton').innerHTML = d.next_action.key === 'export-tier2'
    ? '生成证据包 <span>→</span>'
    : d.next_action.key === 'resume-tier1'
      ? '从断点继续 <span>→</span>'
      : d.next_action.key === 'retry-tier1-data'
        ? '补跑数据缺口 <span>→</span>'
      : '查看候选详情 <span>→</span>';
}

function renderRunSelect() {
  const select = $('#runSelect');
  const selected = state.data.run?.run_id;
  select.innerHTML = state.data.runs.length ? state.data.runs.map(run => `<option value="${esc(run.run_id)}" ${run.run_id === selected ? 'selected' : ''}>${esc(run.as_of_date)} · ${esc(shortId(run.run_id))}</option>`).join('') : '<option value="">暂无批次</option>';
}

function renderPipeline() {
  $('#pipeline').innerHTML = state.data.pipeline.length ? state.data.pipeline.map(stage => {
    const pct = stage.total ? Math.round(stage.passed / stage.total * 100) : 0;
    return `<div class="stage ${stage.total && stage.passed === stage.total ? 'complete' : ''}"><div class="stage-marker">${stage.key}</div><div class="stage-copy"><strong>${esc(stage.name)}</strong><span>${esc(stage.caption)}</span></div><div class="stage-count">${stage.passed} / ${stage.total}</div><div class="stage-progress"><i style="width:${pct}%"></i></div></div>`;
  }).join('') : '<div class="empty-state"><p>启动筛选后显示研究漏斗</p></div>';
}

function renderOverviewCandidates() {
  const rows = state.data.candidates.slice(0, 5);
  $('#overviewCandidates').innerHTML = rows.map(c => `<tr>
    <td>${companyCell(c)}</td><td>${badge(c.screen_status)}</td><td class="metric">${number(c.pe_ttm, '×')}</td>
    <td class="metric ${c.dividend_yield >= .05 ? 'positive' : ''}">${percent(c.dividend_yield)}</td>
    <td>${sparkline(c.revenue_yoy)}</td><td>${badge(c.stage_b_status)}</td>
    <td><button class="row-action" data-detail="${c.symbol}" aria-label="查看详情"><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button></td></tr>`).join('');
  $('#overviewEmpty').classList.toggle('hidden', rows.length > 0);
}

function filteredCandidates() {
  return state.data.candidates || [];
}

function renderCandidateTable() {
  if (!state.data) return;
  const rows = filteredCandidates();
  $('#candidateCount').textContent = `${state.candidatePage.total} 条结果`;
  const activeCount = Number(Boolean(state.query)) + Object.values(state.filters).filter(value => value !== 'ALL').length;
  $('#activeFilterCount').textContent = `${activeCount} 项筛选`;
  $('#activeFilterCount').classList.toggle('hidden', activeCount === 0);
  $('#resetFilters').classList.toggle('hidden', activeCount === 0 && !state.sort.key);
  $$('[data-sort]').forEach(button => {
    const active = button.dataset.sort === state.sort.key;
    button.classList.toggle('active', active);
    $('.sort-icon', button).textContent = active ? (state.sort.direction === 'asc' ? '↑' : '↓') : '↕';
    button.closest('th').setAttribute('aria-sort', active ? (state.sort.direction === 'asc' ? 'ascending' : 'descending') : 'none');
  });
  $('#allCandidates').innerHTML = rows.map(c => `<tr><td>${companyCell(c)}</td><td>${badge(c.screen_status)}</td><td>${badge(c.data_status)}</td><td class="metric">${number(c.pe_ttm, '×')}</td><td class="metric ${c.dividend_yield >= .05 ? 'positive' : ''}">${percent(c.dividend_yield)}</td><td>${badge(c.stage_b_status)}</td><td>${badge(c.stage_c_status)}</td><td><button class="row-action" data-detail="${c.symbol}"><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button></td></tr>`).join('');
  $('#candidateEmpty').classList.toggle('hidden', rows.length > 0);
  renderCandidatePagination();
}

function populateStageFilters() {
  const populate = (selector, key, field) => {
    const select = $(selector);
    const facetKey = field === 'stage_b_status' ? 'stage_b' : 'stage_c';
    const values = state.candidatePage.facets?.[facetKey] || [];
    if (!values.includes(state.filters[key])) state.filters[key] = 'ALL';
    select.innerHTML = `<option value="ALL">全部状态</option>${values.map(value => `<option value="${esc(value)}">${esc(statusLabels[value] || value)}</option>`).join('')}`;
    select.value = state.filters[key];
  };
  populate('#stageBFilter', 'stageB', 'stage_b_status');
  populate('#stageCFilter', 'stageC', 'stage_c_status');
}

function toggleCandidateSort(key) {
  if (state.sort.key === key) state.sort.direction = state.sort.direction === 'asc' ? 'desc' : 'asc';
  else state.sort = { key, direction: 'asc' };
  state.candidatePage.page = 1;
  loadCandidates();
}

function resetCandidateFilters() {
  state.query = '';
  state.filters = { stageA: 'ALL', data: 'ALL', pe: 'ALL', dividend: 'ALL', stageB: 'ALL', stageC: 'ALL' };
  state.sort = { key: null, direction: 'asc' };
  $('#candidateSearch').value = '';
  $$('[data-filter-key]').forEach(select => { select.value = 'ALL'; });
  state.candidatePage.page = 1;
  loadCandidates();
}

async function loadCandidates(render=true) {
  if (!state.data?.run) return;
  const params = new URLSearchParams({
    run_id: state.data.run.run_id,
    page: String(state.candidatePage.page),
    page_size: String(state.candidatePage.pageSize),
    q: state.query,
    ...state.filters
  });
  if (state.sort.key) {
    params.set('sort', state.sort.key);
    params.set('direction', state.sort.direction);
  }
  const response = await fetch(`/api/strategies/golden-pit/candidates?${params}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '候选列表载入失败');
  state.data.candidates = data.items;
  state.data.candidate_total = data.summary?.total ?? data.total;
  state.candidatePage = {page:data.page, pageSize:data.page_size, total:data.total, pages:data.pages, facets:data.facets};
  if (render) { populateStageFilters(); renderOverviewCandidates(); renderCandidateTable(); }
}

async function loadQuality(render=true) {
  if (!state.data?.run) return;
  const params = new URLSearchParams({run_id:state.data.run.run_id, page:'1', page_size:'200'});
  const response = await fetch(`/api/strategies/golden-pit/quality?${params}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '质量记录载入失败');
  state.data.quality = data;
  if (render) renderQuality();
}

function changeCandidatePage(delta) {
  const target = Math.max(1, Math.min(state.candidatePage.pages, state.candidatePage.page + delta));
  if (target === state.candidatePage.page) return;
  state.candidatePage.page = target;
  loadCandidates();
}

function renderCandidatePagination() {
  $('#candidatePageInfo').textContent = `第 ${state.candidatePage.page} / ${state.candidatePage.pages} 页`;
  $('#candidatePrev').disabled = state.candidatePage.page <= 1;
  $('#candidateNext').disabled = state.candidatePage.page >= state.candidatePage.pages;
}

function renderQuality() {
  const q = state.data.quality;
  const gate = $('#qualityGate');
  $('strong', gate).textContent = q.gate_passed === null ? '尚未评估' : q.gate_passed ? '允许继续' : '已阻断';
  $('.health-dot', gate).style.background = q.gate_passed === false ? '#b8584f' : '#5cc59b';
  $('#qualitySummary').innerHTML = `<div class="quality-stat"><span>评估项</span><strong>${q.total ?? q.items.length}</strong></div><div class="quality-stat"><span>非阻断警告</span><strong>${q.warning_count}</strong></div><div class="quality-stat"><span>阻断问题</span><strong>${q.blocking_count}</strong></div>`;
  $('#qualityList').innerHTML = q.items.map(item => `<div class="quality-item"><div class="provider"><strong>${esc(item.provider)}</strong><span>${esc(groupLabel(item.field_group))}</span></div><span class="symbol-field">${esc(item.symbol || '全局股票池')}</span><span class="capability">${esc(item.capability)}</span><span class="issue" title="${esc(issueText(item))}">${esc(issueText(item))}</span>${badge(item.blocking ? 'ERROR' : item.severity)}</div>`).join('');
  $('#qualityEmpty').classList.toggle('hidden', q.items.length > 0);
}

function renderRuns() {
  const runs = state.data.runs;
  $('#runList').innerHTML = runs.map(run => {
    const total = run.universe_size ?? run.progress?.total;
    const recovery = run.progress?.recovery || {};
    const controls = run.status === 'RUNNING'
      ? `<button class="recovery-button" data-run-control="pause" data-run-id="${esc(run.run_id)}">Ⅱ 暂停运行</button><button class="recovery-button danger" data-run-control="stop" data-run-id="${esc(run.run_id)}">■ 停止运行</button>`
      : run.status === 'PAUSED'
        ? `<button class="recovery-button" data-run-control="resume" data-run-id="${esc(run.run_id)}">▶ 恢复运行</button><button class="recovery-button danger" data-run-control="stop" data-run-id="${esc(run.run_id)}">■ 停止运行</button>`
        : '';
    const actions = `${controls}${recovery.can_resume && run.status !== 'PAUSED' ? `<button class="recovery-button" data-recovery="resume" data-run-id="${esc(run.run_id)}"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v6h6"/></svg>从断点继续 <span>${recovery.unfinished_count} 只</span></button>` : ''}${recovery.can_retry_data ? `<button class="recovery-button warning" data-recovery="data" data-run-id="${esc(run.run_id)}"><svg viewBox="0 0 24 24"><path d="M12 3v6l4 2"/><circle cx="12" cy="12" r="9"/></svg>补跑数据缺口 <span>${recovery.data_gap_count} 只</span></button>` : ''}`;
    const controlledAt = run.manual_control ? `<span class="control-note">${esc(statusLabels[run.status] || run.status)} · ${esc(run.manual_control.actor)} · ${formatTime(run.manual_control.created_at)}</span>` : '';
    return `<article class="run-card ${run.run_id === state.data.run?.run_id ? 'selected' : ''}" data-run="${esc(run.run_id)}"><div class="run-primary"><strong>${esc(run.as_of_date)} 点时筛选</strong><span>${esc(run.run_id)}</span>${controlledAt}</div><div class="run-meta"><span>股票池</span><strong>${total ?? '—'} 只</strong></div><div class="run-meta run-version"><span>计算版本</span><strong>${esc(run.calculation_version)}</strong></div><div class="run-meta"><span>${run.status === 'RUNNING' ? '开始时间' : '状态时间'}</span><strong>${formatTime(run.finished_at || run.started_at)}</strong></div>${badge(run.status)}${['RUNNING','PAUSED','INTERRUPTED'].includes(run.status) ? progressMarkup(run.progress) : ''}${actions ? `<div class="run-recovery-actions">${actions}</div>` : ''}</article>`;
  }).join('');
  $('#runsEmpty').classList.toggle('hidden', runs.length > 0);
}

async function controlRun(action, runId) {
  const copy = {
    pause: ['暂停运行', '暂停后将安全终止当前 Worker，可稍后从断点恢复。'],
    resume: ['恢复运行', '将沿用原 run_id 和固化股票池，从未完成标的继续。'],
    stop: ['停止运行', '停止后该运行进入终态，不能再次恢复。']
  }[action];
  if (!copy || !window.confirm(`${copy[1]}\n\n确认${copy[0]}？`)) return;
  const actor = window.prompt('请输入操作者标识，用于审计记录', 'web-operator');
  if (!actor) return;
  try {
    const url = `/api/strategies/golden-pit/actions/${action}-run`;
    const payload = {run_id:runId, actor, reason:`Web 控制台${copy[0]}`};
    let response = await postControl(url, payload);
    if (response.status === 403) {
      const token = window.prompt('请输入平台变更令牌');
      if (!token) return;
      sessionStorage.setItem('platformApiToken', token);
      response = await postControl(url, payload);
    }
    const data = await response.json(); if (!response.ok) throw new Error(data.error || `${copy[0]}失败`);
    toast(`${copy[0]}指令已执行`, action === 'resume' ? '断点续跑任务已进入队列。' : '旧 Worker 已被 fencing，不能继续提交结果。');
    await loadOverview(runId); await loadJobs();
  } catch (error) { toast(`${copy[0]}失败`, error.message, true); }
}

function postControl(url, payload) {
  const token = sessionStorage.getItem('platformApiToken') || '';
  const headers = {'Content-Type':'application/json'};
  if (token) headers['X-Platform-Token'] = token;
  return fetch(url, {method:'POST', headers, body:JSON.stringify(payload)});
}

async function startRecovery(mode, runId) {
  const dataRetry = mode === 'data';
  const message = dataRetry
    ? '将重新获取未产生决策、DATA_ERROR 和 PENDING_DATA 标的，不会重跑正常完成标的。是否继续？'
    : '将使用固化股票池跳过已完成标的，从断点继续。是否继续？';
  if (!window.confirm(message)) return;
  try {
    const action = dataRetry ? 'retry-data' : 'resume';
    const response = await fetch(`/api/strategies/golden-pit/actions/${action}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({run_id:runId})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '启动失败');
    toast(dataRetry ? '数据缺口补跑已启动' : '断点续跑已启动', '任务将沿用原 run_id，并保留逐股尝试记录。');
    navigate('runs'); await loadJobs(); await loadOverview(runId);
  } catch (error) { toast(dataRetry ? '无法启动补跑' : '无法继续运行', error.message, true); }
}

function openDrawer(symbol) {
  const c = state.data.candidates.find(item => item.symbol === symbol);
  if (!c) return;
  state.selected = c;
  $('#drawerTitle').textContent = c.stock_name;
  $('#drawerSymbol').textContent = `${c.symbol} · 研究时点 ${state.data.run.as_of_date}`;
  const pePass = c.pe_ttm != null && c.pe_ttm < 15;
  const divPass = c.dividend_yield != null && c.dividend_yield > .05;
  const legacyStrict = Boolean(state.data.run?.config?.strict_improvement) || state.data.run?.config?.trend_rule === 'STRICT_IMPROVEMENT';
  const revPass = trendPass(c.revenue_yoy);
  const profitPass = trendPass(c.profit_yoy);
  const revenueRule = legacyStrict ? '营收同比严格逐季改善' : '营收同比连续两个季度正增长';
  const profitRule = legacyStrict ? '归母净利润同比严格逐季改善' : '归母净利润同比连续两个季度正增长';
  $('#drawerBody').innerHTML = `
    <section class="detail-section"><h3>核心指标</h3><div class="detail-kpis"><div class="detail-kpi"><span>PE (TTM)</span><strong>${number(c.pe_ttm, '×')}</strong></div><div class="detail-kpi"><span>${c.latest_fiscal_year ? `${esc(c.latest_fiscal_year)}年度股息率` : '最新完整年度股息率'}</span><strong>${percent(c.dividend_yield)}</strong></div><div class="detail-kpi"><span>风险警示</span><strong>${c.risk_warning ? '是' : '否'}</strong></div></div></section>
    <section class="detail-section"><h3>连续单季度同比趋势</h3>${trendChart(c)}<div class="chart-legend"><span><i></i>营业收入</span><span class="profit"><i></i>归母净利润</span></div></section>
    <section class="detail-section"><h3>量化初筛条件</h3><div class="condition-list">${condition('PE (TTM) < 15', pePass, number(c.pe_ttm, '×'))}${condition('最新完整会计年度税前股息率 > 5%', divPass, percent(c.dividend_yield))}${condition(revenueRule, revPass, sequence(c.revenue_yoy))}${condition(profitRule, profitPass, sequence(c.profit_yoy))}${condition('非 ST / 风险警示', !c.risk_warning, c.risk_warning ? '风险警示' : '正常')}</div></section>
    ${tier2Research(c.stage_b)}
    ${c.quality_warnings.length ? `<section class="detail-section"><h3>数据提示</h3><ul class="warning-list">${c.quality_warnings.map(item => `<li>${esc(item)}</li>`).join('')}</ul></section>` : ''}
    <section class="detail-section"><h3>研究阶段</h3><div class="stage-timeline">${stageLine('A', '量化初筛', c.screen_status)}${stageLine('B', '证据研究', c.stage_b_status)}${stageLine('C', '风险终审', c.stage_c_status)}</div></section>`;
  renderDrawerFooter(c);
  $('#detailDrawer').classList.add('open'); $('#detailDrawer').setAttribute('aria-hidden', 'false'); $('#scrim').classList.add('open');
}

function renderDrawerFooter(c) {
  const footer = $('#drawerFooter');
  if (c.stage_b_status === '待生成证据包') {
    footer.innerHTML = '<button class="primary-button" id="exportTier2">生成证据研究包</button>';
    $('#exportTier2').addEventListener('click', () => exportTier2([c.symbol]));
  } else if (c.stage_b_status === '待人工复核') {
    footer.innerHTML = '<button class="primary-button" id="reviewB">提交证据研究复核</button>';
    $('#reviewB').addEventListener('click', () => openReview('B', c));
  } else if (c.stage_c_status === '待人工复核') {
    footer.innerHTML = '<button class="primary-button" id="reviewC">提交风险终审</button>';
    $('#reviewC').addEventListener('click', () => openReview('C', c));
  } else {
    footer.innerHTML = '<button class="secondary-button" id="drawerCloseAction">关闭详情</button>';
    $('#drawerCloseAction').addEventListener('click', closeDrawer);
  }
}

function closeDrawer() { $('#detailDrawer').classList.remove('open'); $('#detailDrawer').setAttribute('aria-hidden', 'true'); $('#scrim').classList.remove('open'); state.selected = null; }

function openReview(stage, c) {
  const form = $('#reviewForm'); form.reset();
  form.elements.stage.value = stage; form.elements.symbol.value = c.symbol;
  form.elements.assessment_id.value = c.stage_b.assessment_id || '';
  form.elements.risk_assessment_id.value = c.stage_c.risk_assessment_id || '';
  $('#reviewStage').textContent = `${stage === 'B' ? '证据研究' : '风险终审'} · HUMAN REVIEW`;
  $('#reviewTitle').textContent = `${c.stock_name} 人工复核`;
  const system = stage === 'B' ? c.stage_b.system_recommendation : c.stage_c.system_status;
  [...form.elements.decision.options].forEach(option => { option.disabled = rank(option.value) > rank(system); });
  form.elements.decision.value = [...form.elements.decision.options].find(o => !o.disabled)?.value || 'REJECT';
  closeDrawer(); $('#reviewModal').showModal();
}

async function submitReview(event) {
  event.preventDefault();
  const form = event.currentTarget, stage = form.elements.stage.value;
  const payload = { run_id: state.data.run.run_id, symbol: form.elements.symbol.value, decision: form.elements.decision.value, reviewer: form.elements.reviewer.value, rationale: form.elements.rationale.value };
  if (stage === 'B') payload.assessment_id = form.elements.assessment_id.value; else payload.risk_assessment_id = form.elements.risk_assessment_id.value;
  const submit = $('button[type="submit"]', form); submit.disabled = true;
  try {
    const response = await fetch(`/api/strategies/golden-pit/actions/review-stage-${stage.toLowerCase()}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '提交失败');
    $('#reviewModal').close(); toast('复核已记录', `${payload.symbol} · ${payload.decision}`); await loadOverview(state.data.run.run_id);
  } catch (error) { toast('复核提交失败', error.message, true); }
  finally { submit.disabled = false; }
}

async function startWorkflow(event) {
  event.preventDefault(); const form = event.currentTarget;
  const payload = { scope: form.elements.scope.value, as_of: form.elements.as_of.value, symbols: form.elements.symbols.value };
  const submit = $('button[type="submit"]', form); submit.disabled = true;
  try {
    const response = await fetch('/api/strategies/golden-pit/actions/run', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '启动失败');
    $('#workflowModal').close(); toast('筛选已在后台启动', '可在“运行记录”查看任务进度。'); navigate('runs'); await loadJobs();
  } catch (error) { toast('无法启动筛选', error.message, true); }
  finally { submit.disabled = false; }
}

function updateWorkflowScope() {
  const form = $('#workflowForm'); if (!form) return;
  const market = form.elements.scope.value === 'market';
  $('.symbols-field', form).classList.toggle('hidden', market);
  form.elements.symbols.required = !market;
  $('#workflowSubmit').textContent = market ? '开始全市场筛选' : '启动指定股票筛选';
  $('#workflowNoticeTitle').textContent = market ? '将扫描全市场股票池' : '将筛选指定股票';
  $('#workflowNoticeDetail').textContent = market
    ? '任务会访问已配置的数据源并在后台运行，股票数量较多时可能需要较长时间。超出近期窗口的历史日期需要精确点时股票池。'
    : '任务会访问已配置的数据源，耗时取决于代码数量和网络状况。';
}

async function exportTier2(symbols) {
  try {
    const response = await fetch('/api/strategies/golden-pit/actions/export-evidence', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({run_id:state.data.run.run_id, symbols}) });
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '启动失败');
    closeDrawer(); toast('证据包生成任务已启动', symbols.join('、')); navigate('runs'); await loadJobs();
  } catch (error) { toast('无法生成证据包', error.message, true); }
}

async function loadJobs() {
  try {
    const response = await fetch('/api/jobs'); const data = await response.json();
    const runningRuns = (data.running_runs || []).filter(run => run.strategy_id === 'golden-pit');
    let jobs = data.jobs || [];
    let runIndex = 0;
    jobs = jobs.map(job => job.status === 'RUNNING' && runningRuns[runIndex]
      ? {...job, progress: runningRuns[runIndex++].progress}
      : job);
    for (; runIndex < runningRuns.length; runIndex++) {
      const run = runningRuns[runIndex];
      jobs.push({job_id:`run:${run.run_id}`, label:`${run.as_of_date} 全市场量化初筛`, status:'RUNNING', output:'', progress:run.progress});
    }
    $('#jobsPanel').classList.toggle('hidden', !jobs.length);
    $('#jobList').innerHTML = jobs.map(job => `<div class="job-row"><strong>${esc(job.label)}</strong>${badge(job.status)}${job.status === 'RUNNING' ? progressMarkup(job.progress, true) : ''}${job.output ? `<p>${esc(job.output)}</p>` : (job.status === 'RUNNING' ? '<p class="job-hint">正在持续写入正式筛选结果，进度每 4 秒更新。</p>' : '')}</div>`).join('');
    clearTimeout(state.jobsTimer);
    if (jobs.some(job => ['QUEUED','RUNNING'].includes(job.status))) state.jobsTimer = setTimeout(async () => {
      state.overviewPollTick += 1;
      await loadJobs();
      if (state.overviewPollTick % 3 === 0) await loadOverview(state.data?.run?.run_id || '');
    }, 4000);
  } catch (_) { /* non-critical background status */ }
}

function nextAction() {
  const action = state.data.next_action;
  if (action.key === 'export-tier2') exportTier2([]);
  else if (action.key === 'resume-tier1') startRecovery('resume', state.data.run.run_id);
  else if (action.key === 'retry-tier1-data') startRecovery('data', state.data.run.run_id);
  else navigate('candidates');
}

function navigate(page) {
  state.page = page; $$('.page').forEach(p => p.classList.remove('active')); $(`#page-${page}`).classList.add('active');
  $$('#goldenPitNav .nav-item').forEach(item => item.classList.toggle('active', item.dataset.page === page));
  const labels = { overview:'策略看板', candidates:'候选雷达', quality:'数据质量', runs:'运行记录' }; $('#pageTitle').textContent = `黄金坑 · ${labels[page]}`;
  $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('open'); window.scrollTo({top:0,behavior:'smooth'});
  if (page === 'runs') loadJobs();
}

function companyCell(c) { return `<div class="company"><span class="company-mark">${esc(c.stock_name.slice(0,1))}</span><div><strong>${esc(c.stock_name)}</strong><span>${esc(c.symbol)}</span></div></div>`; }
function badge(status) { const raw = String(status ?? '—'); const cls = ['PASS','FAIL','SUPERSEDED','REJECT','ERROR','COMPLETE','FINISHED','FINISHED_WITH_ERRORS','REVIEW','PENDING_DATA','DATA_ERROR','QUEUED','RUNNING','PAUSED','CANCELLED','SUCCEEDED','FAILED','INTERRUPTED'].includes(raw) ? raw : (raw.startsWith('待') ? 'pending' : 'neutral'); return `<span class="badge ${cls}">${esc(statusLabels[raw] || raw)}</span>`; }
function number(value, suffix='') { return value == null ? '—' : `${fmt.format(value)}${suffix}`; }
function percent(value) { return value == null ? '—' : `${fmt.format(value * 100)}%`; }
function sequence(values) { return values?.length ? values.map(v => `${fmt.format(v*100)}%`).join(' → ') : '—'; }
function shortId(value) { return String(value).slice(0, 8); }
function formatTime(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value).slice(0,16) : new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date); }
function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '正在采集速度样本';
  if (seconds < 60) return '不足 1 分钟';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `约 ${minutes} 分钟`;
  const hours = Math.floor(minutes / 60), remain = minutes % 60;
  if (hours < 24) return `约 ${hours} 小时${remain >= 10 ? ` ${remain} 分` : ''}`;
  const days = Math.floor(hours / 24), remainHours = hours % 24;
  return `约 ${days} 天${remainHours ? ` ${remainHours} 小时` : ''}`;
}
function progressMarkup(progress, compact=false) {
  const processed = progress?.processed ?? 0, total = progress?.total;
  const percent = progress?.percent ?? (total ? processed / total * 100 : 0);
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  const countText = total ? `${fmt.format(processed)} / ${fmt.format(total)} 只` : `${fmt.format(processed)} 只已完成`;
  const etaText = progress?.eta_seconds != null ? `预计剩余 ${formatDuration(progress.eta_seconds)}` : formatDuration(null);
  return `<div class="run-progress ${compact ? 'compact' : ''}"><div class="progress-copy"><strong>${countText}</strong><span>${safePercent.toFixed(1)}% · ${etaText}<em>ETA 会随数据源速度动态调整</em></span></div><div class="progress-track" role="progressbar" aria-valuenow="${safePercent.toFixed(1)}" aria-valuemin="0" aria-valuemax="100"><i style="width:${safePercent}%"></i></div>${sourceHealthMarkup(progress?.source_health)}</div>`;
}
function sourceHealthMarkup(health) {
  if (!health) return '';
  const icons = {HEALTHY:'✓', RECOVERED:'↗', DEGRADED:'!', RATE_LIMITED:'Ⅱ', NETWORK_ISSUE:'!', WAITING:'…', STALLED:'!'};
  const idle = health.idle_seconds == null ? '等待首次请求' : health.idle_seconds < 10 ? '刚刚有响应' : `${formatDuration(health.idle_seconds)}前有响应`;
  const lastError = health.last_error ? `最近异常：${health.last_error.symbol || '全局'} · ${groupLabel(health.last_error.field_group)} · ${health.last_error.error_type || health.last_error.provider}` : '';
  return `<div class="source-health-banner ${esc(health.status)} ${esc(health.severity)}"><i>${icons[health.status] || '•'}</i><div><strong>${esc(health.label)}</strong><p>${esc(health.message)}</p>${lastError ? `<small>${esc(lastError)}</small>` : ''}</div><span>${esc(idle)}</span></div>`;
}
function strictlyImproving(values) { return Array.isArray(values) && values.length >= 3 && values.every((v,i) => i === 0 || v > values[i-1]); }
function consecutivePositive(values) { return Array.isArray(values) && values.length === 2 && values.every(value => value != null && value > 0); }
function trendPass(values) { return state.data?.run?.config?.strict_improvement || state.data?.run?.config?.trend_rule === 'STRICT_IMPROVEMENT' ? strictlyImproving(values) : consecutivePositive(values); }
function rank(value) { return ({REJECT:0, REVIEW:1, PASS:2})[value] ?? -1; }
function groupLabel(group) { return ({universe:'股票池',market:'行情估值',financial_statements:'财务报表',dividend_and_actions:'分红与公司行动',risk_warning_status:'风险警示'})[group] || group; }
function issueText(item) { return item.issues?.map(i => i.message).join('；') || '未发现问题'; }
function condition(label, pass, actual) { return `<div class="condition ${pass ? '' : 'fail'}"><i class="condition-icon">${pass ? '✓' : '!'}</i><span>${esc(label)}</span><small>${esc(actual)}</small></div>`; }
function stageLine(key, label, status) { return `<div class="stage-line"><i>${key}</i><strong>${label}</strong>${badge(status)}</div>`; }

const dimensionLabels = {
  demand_durability: '需求持续性', competitive_position: '竞争地位',
  dividend_sustainability: '分红可持续性', earnings_quality: '盈利质量',
  market_mispricing: '市场错价', risk_reward_asymmetry: '风险收益不对称',
  long_cycle_fit: '长周期适配度'
};
const scenarioLabels = { PESSIMISTIC:'悲观', BASE:'基准', OPTIMISTIC:'乐观' };
const riskLabels = { LOW:'低', MEDIUM:'中', HIGH:'高', UNKNOWN:'未知' };
function researchList(title, items, tone='') {
  if (!Array.isArray(items) || !items.length) return '';
  return `<div class="research-list ${tone}"><h5>${esc(title)}</h5><ul>${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>`;
}
function tier2Research(stageB) {
  const a = stageB?.assessment;
  if (!a) return '';
  const dimensions = (a.dimensions || []).map(item => {
    const confidence = item.confidence == null ? '—' : `${Math.round(item.confidence * 100)}%`;
    const sourceText = (item.sources || []).map(source => [source.title, source.date, source.page_or_section].filter(Boolean).join(' · '));
    return `<details class="research-dimension">
      <summary><span>${esc(dimensionLabels[item.dimension] || item.dimension)}</span>${badge(item.verdict)}<small>置信度 ${esc(confidence)}</small></summary>
      <div class="research-dimension-body">
        <p class="dimension-summary">${esc(item.reasoning_summary || '暂无总结')}</p>
        ${researchList('事实', item.facts)}
        ${researchList('推断', item.inferences)}
        ${researchList('反方证据', item.counter_evidence, 'counter')}
        ${researchList('证伪条件', item.falsification_conditions, 'falsification')}
        ${researchList('证据来源', sourceText, 'sources')}
      </div>
    </details>`;
  }).join('');
  const scenarios = (a.scenario_analysis || []).map(item => `<article class="scenario-card ${esc(item.scenario)}">
    <div><span>${esc(scenarioLabels[item.scenario] || item.scenario)}</span><small>永久损失风险 ${esc(riskLabels[item.permanent_loss_risk] || item.permanent_loss_risk)}</small></div>
    <strong>${item.value_per_share == null ? '—' : `${number(item.value_per_share)} 元`}</strong>
    <p>3年年化 ${percent(item.annualized_return_3y)} · 5年年化 ${percent(item.annualized_return_5y)}</p>
    <ul>${(item.assumptions || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul>
  </article>`).join('');
  const provider = [stageB.ai_provider || a.ai_provider, stageB.ai_model || a.ai_model].filter(Boolean).join(' · ');
  return `<section class="detail-section tier2-research">
    <div class="research-heading"><div><span class="overline">AI EVIDENCE RESEARCH</span><h3>AI 证据研究</h3></div><div class="research-status">${badge(stageB.system_recommendation || a.recommendation)}<small>系统建议</small></div></div>
    <div class="research-meta"><span>评估 ${esc(stageB.assessment_id || '—')}</span><span>${esc(provider || 'AI研究')}</span><span>导入 ${esc(formatTime(stageB.imported_at))}</span></div>
    <div class="research-conclusion"><h4>结论摘要</h4><p>${esc(a.overall_reasoning || '暂无总体结论')}</p></div>
    <h4 class="research-subtitle">情景估值</h4><div class="scenario-grid">${scenarios}</div>
    <h4 class="research-subtitle">七维证据判断</h4><div class="research-dimensions">${dimensions}</div>
    <div class="research-overall-evidence">${researchList('总体反方证据', a.overall_counter_evidence, 'counter')}${researchList('总体证伪条件', a.falsification_conditions, 'falsification')}</div>
  </section>`;
}

function sparkline(values) {
  if (!values?.length) return '<span class="metric">—</span>';
  const w=70,h=26,p=2,min=Math.min(...values),max=Math.max(...values),range=max-min || 1;
  const pts=values.map((v,i)=>[p+i*(w-2*p)/Math.max(values.length-1,1),h-p-(v-min)/range*(h-2*p)]);
  const line=pts.map((q,i)=>`${i?'L':'M'}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' ');
  const area=`${line} L${pts.at(-1)[0]},${h} L${pts[0][0]},${h} Z`;
  return `<svg class="sparkline ${trendPass(values)?'':'bad'}" viewBox="0 0 ${w} ${h}"><path class="area" d="${area}"/><path class="line" d="${line}"/></svg>`;
}

function trendChart(c) {
  const values=[...c.revenue_yoy,...c.profit_yoy].filter(v=>Number.isFinite(v)); if (!values.length) return '<div class="empty-state"><p>暂无可比季度数据</p></div>';
  const w=420,h=130,p={l:20,r:12,t:10,b:20},min=Math.min(...values,0),max=Math.max(...values,0),range=max-min||1;
  const point=(v,i,n)=>[p.l+i*(w-p.l-p.r)/Math.max(n-1,1),p.t+(max-v)/range*(h-p.t-p.b)];
  const path=arr=>arr.map((v,i)=>{const q=point(v,i,arr.length);return `${i?'L':'M'}${q[0].toFixed(1)},${q[1].toFixed(1)}`}).join(' ');
  const zero=point(0,0,2)[1];
  const labels=c.quarters.map((q,i)=>{const x=point(0,i,c.quarters.length)[0];return `<text x="${x}" y="126" text-anchor="middle" fill="#899691" font-size="8">${esc(q.slice(5,7))}月</text>`}).join('');
  return `<svg class="trend-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="grid" d="M20,32H408 M20,72H408 M20,112H408"/><path class="zero" d="M20,${zero}H408"/><path class="rev" d="${path(c.revenue_yoy)}"/><path class="profit" d="${path(c.profit_yoy)}"/>${labels}</svg>`;
}

function setLoading(value) { $('#loadingBar').classList.toggle('loading', value); $('#refreshButton').disabled = value; }
function toast(title, detail='', error=false) { const el=document.createElement('div'); el.className=`toast ${error?'error':''}`; el.innerHTML=`<div>${error?'!':'✓'}</div><div><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`; $('#toastStack').append(el); setTimeout(()=>el.remove(),4500); }
function esc(value) { return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch])); }

window.StrategyConsole.register({
  id: 'golden-pit',
  mount,
  activate() { loadOverview(state.data?.run?.run_id || ''); loadJobs(); },
  deactivate() { clearTimeout(state.jobsTimer); closeDrawer(); },
  navigate
});
})();
