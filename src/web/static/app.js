const StrategyConsole = (() => {
  const modules = new Map();
  const loadedScripts = new Set();
  const loadedTemplates = new Set();
  let ready = false;
  let activeStrategy = null;
  let catalog = [];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  const statusLabels = {ACTIVE:'运行中', BETA:'试运行', PAUSED:'已暂停', RUNNING:'运行中', FINISHED:'已完成', FINISHED_WITH_ERRORS:'完成但有异常', INTERRUPTED:'已中断'};
  const reportActions = {DRAFT:[['validate','自动校验']], VALIDATED:[['review','送交审核'],['reject','驳回']], IN_REVIEW:[['publish','批准发布'],['reject','驳回']]};
  const releaseActions = {DRAFT:[['validate','验证通过']], VALIDATED:[['shadow','进入 Shadow']], SHADOW:[['production','发布生产'],['disable','停用']], PRODUCTION:[['disable','停用']], DISABLED:[['shadow','恢复 Shadow'],['archive','归档']]};

  async function responseJson(response, fallbackMessage) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      throw new Error(response.status === 404
        ? '当前后台版本与页面不匹配，请重启服务后刷新页面'
        : `${fallbackMessage}（后台返回了非 JSON 响应）`);
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || fallbackMessage);
    return data;
  }

  function showError(error) {
    const stack = $('#toastStack');
    const toast = document.createElement('div');
    toast.className = 'toast error';
    toast.setAttribute('role', 'alert');
    toast.textContent = error?.message || String(error);
    stack.appendChild(toast);
    window.setTimeout(() => toast.remove(), 6000);
  }

  function register(module) {
    if (!module?.id || typeof module.mount !== 'function') throw new Error('策略展示模块必须提供 id 和 mount()');
    if (modules.has(module.id)) throw new Error(`策略展示模块重复注册: ${module.id}`);
    modules.set(module.id, module);
    if (ready) mount(module);
  }

  function mount(module) {
    if (module.__mounted) return;
    module.mount({ openHome, openStrategy });
    module.__mounted = true;
  }

  async function loadCatalog() {
    const response = await fetch('/api/strategies');
    const data = await responseJson(response, '策略目录载入失败');
    catalog = data.strategies || [];
    $('#strategyCount').textContent = catalog.length;
    $('#strategyNavCount').textContent = catalog.length;
    renderCatalog();
  }

  async function loadHealth() {
    const badge = $('#platformHealth');
    const label = $('#platformHealthText');
    try {
      const response = await fetch('/api/health', {cache: 'no-store'});
      const data = await responseJson(response, '服务未就绪');
      if (data.status !== 'ok' || data.database?.status !== 'ready') throw new Error(data.error || '服务未就绪');
      badge.className = 'platform-health';
      label.textContent = `前后端已连接 · ${Number(data.strategies?.count || 0)}个策略`;
      badge.title = `数据库 ${data.database.file} 已就绪；检查时间 ${new Date(data.checked_at).toLocaleString('zh-CN')}`;
    } catch (error) {
      badge.className = 'platform-health error';
      label.textContent = '后端连接异常';
      badge.title = error.message;
    }
  }

  async function loadUiTemplate(strategy) {
    if (!strategy.ui_template || loadedTemplates.has(strategy.id)) return;
    const response = await fetch(strategy.ui_template);
    if (!response.ok) throw new Error(`无法载入策略页面模板: ${strategy.ui_template}`);
    const source = await response.text();
    const documentTemplate = new DOMParser().parseFromString(source, 'text/html');
    const navigation = documentTemplate.querySelector(`[data-strategy-nav="${strategy.id}"]`);
    const pages = [...documentTemplate.querySelectorAll(`[data-strategy-page="${strategy.id}"]`)];
    if (!navigation || !pages.length) throw new Error(`策略 ${strategy.short_name} 的页面模板不完整`);
    const strategyEntry = $(`[data-open-strategy="${CSS.escape(strategy.id)}"]`);
    if (!strategyEntry) throw new Error(`策略 ${strategy.short_name} 未出现在策略中心`);
    strategyEntry.insertAdjacentElement('afterend', navigation);
    pages.forEach(page => $('#strategyWorkspace').append(page));
    ['detailDrawer', 'workflowModal', 'reviewModal'].forEach(id => {
      const overlay = documentTemplate.getElementById(id);
      if (overlay) $('#strategyOverlays').append(overlay);
    });
    loadedTemplates.add(strategy.id);
  }

  async function loadUiModule(strategy) {
    await loadUiTemplate(strategy);
    if (modules.has(strategy.id) || !strategy.ui_module || loadedScripts.has(strategy.ui_module)) return Promise.resolve();
    loadedScripts.add(strategy.ui_module);
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = strategy.ui_module;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`无法载入策略展示模块: ${strategy.ui_module}`));
      document.head.appendChild(script);
    });
  }

  function renderCatalog() {
    $('#strategyCatalogNav').innerHTML = catalog.map(strategy => `<button class="nav-item strategy-entry" data-open-strategy="${esc(strategy.id)}"><span class="strategy-nav-mark">${esc(strategy.short_name.slice(0, 1))}</span><span>${esc(strategy.short_name)}</span><i class="strategy-state-dot ${esc(strategy.status.toLowerCase())}"></i></button>`).join('');
    $('#strategyGrid').innerHTML = catalog.map(strategy => {
      const run = strategy.latest_run;
      const metrics = (strategy.metrics || []).map(metric => `<div><span>${esc(metric.label)}</span><strong>${Number(metric.value || 0).toLocaleString('zh-CN')}</strong></div>`).join('');
      const stages = (strategy.stages || []).map((stage, index) => `<span><i>${String.fromCharCode(65 + index)}</i>${esc(stage)}</span>`).join('<b>→</b>');
      return `<article class="strategy-card" data-open-strategy="${esc(strategy.id)}"><div class="strategy-card-top"><span class="strategy-symbol">${esc(strategy.short_name.slice(0, 1))}</span><div><span class="strategy-version">${esc(strategy.version)}</span><h2>${esc(strategy.name)}</h2></div><span class="strategy-status ${esc(strategy.status.toLowerCase())}">${esc(statusLabels[strategy.status] || strategy.status)}</span></div><p>${esc(strategy.description)}</p><div class="strategy-stage-line">${stages}</div><div class="strategy-metrics">${metrics}</div><div class="strategy-card-footer"><span>${run ? `${esc(run.as_of_date)} · ${esc(statusLabels[run.status] || run.status)}` : '尚未运行'}</span><button>进入策略工作台 <i>→</i></button></div></article>`;
    }).join('');
    $('#strategyEmpty').classList.toggle('hidden', catalog.length > 0);
  }

  async function openStrategy(strategyId) {
    const strategy = catalog.find(item => item.id === strategyId);
    if (!strategy) return;
    await loadUiModule(strategy);
    const module = modules.get(strategyId);
    if (!module) throw new Error(`策略 ${strategy.short_name} 尚未提供展示模块`);
    if (activeStrategy && activeStrategy !== strategyId) modules.get(activeStrategy)?.deactivate?.();
    activeStrategy = strategyId;
    mount(module);
    $$('.page').forEach(page => page.classList.remove('active'));
    $$('[data-strategy-nav]').forEach(nav => nav.classList.toggle('hidden', nav.dataset.strategyNav !== strategyId));
    $$('.shell-nav').forEach(item => item.classList.remove('active'));
    $$('.strategy-entry').forEach(item => item.classList.toggle('active', item.dataset.openStrategy === strategyId));
    $$('.strategy-control').forEach(control => control.classList.remove('hidden'));
    module.activate?.(strategy);
    module.navigate?.('overview');
    closeSidebar();
  }

  function openHome() {
    modules.get(activeStrategy)?.deactivate?.();
    activeStrategy = null;
    $$('.page').forEach(page => page.classList.remove('active'));
    $('#page-home').classList.add('active');
    $$('[data-strategy-nav]').forEach(nav => nav.classList.add('hidden'));
    $$('.strategy-control').forEach(control => control.classList.add('hidden'));
    $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.shellPage === 'home'));
    $$('.strategy-entry').forEach(item => item.classList.remove('active'));
    $('#pageTitle').textContent = '策略中心';
    closeSidebar();
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  async function openShellPage(pageId) {
    modules.get(activeStrategy)?.deactivate?.();
    activeStrategy = null;
    $$('.page').forEach(page => page.classList.remove('active'));
    $(`#page-${pageId}`)?.classList.add('active');
    $$('[data-strategy-nav]').forEach(nav => nav.classList.add('hidden'));
    $$('.strategy-control').forEach(control => control.classList.add('hidden'));
    $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.shellPage === pageId));
    $$('.strategy-entry').forEach(item => item.classList.remove('active'));
    const titles = {signals:'统一信号', 'data-center':'数据中心', 'ai-research':'AI 研究中心', integrations:'集成健康', laboratory:'研究实验室', backtests:'回测中心', portfolios:'组合与风险', governance:'策略发布'};
    $('#pageTitle').textContent = titles[pageId] || '策略中心';
    if (pageId === 'signals') await loadSignals();
    if (pageId === 'data-center') await loadDataCenter();
    if (pageId === 'ai-research') await loadResearch();
    if (pageId === 'integrations') await loadIntegrations();
    if (['laboratory','backtests','portfolios','governance'].includes(pageId)) await loadArtifacts(pageId);
    if (pageId === 'governance') await loadSignalGovernance();
    closeSidebar();
  }

  async function loadSignals() {
    const response = await fetch('/api/signals'); const data = await responseJson(response, '统一信号载入失败');
    const items = data.signals || []; $('#signalEmpty').classList.toggle('hidden', items.length > 0);
    $('#signalList').innerHTML = items.map(item => `<article class="strategy-card"><div class="strategy-card-top"><span class="strategy-symbol">${esc(item.symbol.slice(-1))}</span><div><span class="strategy-version">${esc(item.strategy_id)}</span><h2>${esc(item.symbol)}</h2></div><span class="strategy-status active">${esc(item.direction)}</span></div><p>评分 ${Number(item.score).toFixed(2)} · 排名 ${Number(item.rank)} · 置信度 ${(Number(item.confidence) * 100).toFixed(0)}%</p><div class="strategy-card-footer"><span>有效至 ${esc(item.valid_until)}</span><span>${esc(JSON.stringify(item.attribution))}</span></div></article>`).join('');
  }

  async function loadDataCenter() {
    const response = await fetch('/api/data-center/overview'); const data = await responseJson(response, '数据中心载入失败');
    $('#snapshotGrid').innerHTML = data.snapshots.length ? data.snapshots.map(item => `<article class="strategy-card"><span class="strategy-version">${esc(item.dataset_type)}</span><h2>${esc(item.as_of_date)}</h2><p>${Number(item.row_count).toLocaleString('zh-CN')} 行 · ${esc(item.content_hash.slice(0,12))}</p><div class="strategy-card-footer"><span>覆盖率 ${esc(item.quality.coverage ?? '—')}</span><span>${esc(item.created_at)}</span></div></article>`).join('') : '<div class="empty-state panel"><h3>暂无数据快照</h3><p>发布点时 Parquet 快照后会显示质量和血缘。</p></div>';
    $('#egressGrid').innerHTML = data.egress_policies.length ? data.egress_policies.map(item => `<article class="strategy-card"><span class="strategy-version">FIELD POLICY</span><h2>${esc(item.field_path)}</h2><div class="strategy-card-footer"><span>${esc(item.egress_class)}</span><span>${esc(item.mask_rule || '无需脱敏')}</span></div></article>`).join('') : '<div class="empty-state"><p>尚未配置字段外发策略，默认禁止 AI 读取。</p></div>';
  }

  async function loadSignalGovernance() {
    const response = await fetch('/api/governance/signals'); const data = await responseJson(response, '跨策略治理载入失败');
    const cards = [`<article class="strategy-card"><span class="strategy-version">CROSS STRATEGY</span><h2>${Number(data.signal_count)} 条统一信号</h2><p>${Number(data.conflicts.length)} 个方向冲突 · ${Number(data.overlaps.length)} 组重合度</p></article>`];
    data.conflicts.forEach(item => cards.push(`<article class="strategy-card"><span class="strategy-version">CONFLICT</span><h2>${esc(item.symbol)}</h2><p>${item.opinions.map(opinion => `${esc(opinion.strategy_id)} ${esc(opinion.direction)}`).join(' · ')}</p></article>`));
    $('#signalGovernance').innerHTML = cards.join('');
    const governanceResponse = await fetch('/api/governance/overview'); const governance = await responseJson(governanceResponse, '发布治理载入失败');
    $('#releaseGrid').innerHTML = governance.releases.length ? governance.releases.map(item => { const actions = (releaseActions[item.status] || []).map(action => `<button class="primary-button" data-release-action="${esc(action[0])}" data-release-id="${esc(item.release_id)}">${esc(action[1])}</button>`).join(''); return `<article class="strategy-card"><span class="strategy-version">${esc(item.object_type)} · v${Number(item.version)}</span><h2>${esc(item.object_id)}</h2><p>${esc(item.actor)} · ${esc(item.note || '无备注')}</p><div class="strategy-card-footer"><span>${esc(item.status)}</span><span>${esc(item.created_at)}</span></div><div class="topbar-actions">${actions}</div></article>`; }).join('') : '<div class="empty-state"><p>暂无发布对象。</p></div>';
    $('#auditGrid').innerHTML = governance.audit_events.length ? governance.audit_events.map(item => `<article class="strategy-card"><span class="strategy-version">${esc(item.action)}</span><h2>${esc(item.object_id)}</h2><p>${esc(item.actor)} · ${esc(item.payload_hash.slice(0,12))}</p><div class="strategy-card-footer"><span>${esc(item.object_type)}</span><span>${esc(item.created_at)}</span></div></article>`).join('') : '<div class="empty-state"><p>暂无审计事件。</p></div>';
  }

  async function loadResearch() {
    const response = await fetch('/api/ai-research/overview'); const data = await responseJson(response, 'AI 研究中心载入失败');
    $('#researchSummary').innerHTML = [['AI 数据集',data.datasets.length],['提示词版本',data.templates.length],['研究报告',data.reports.length],['Provider',data.providers.length]].map(item => `<article class="strategy-card"><span class="strategy-version">RESEARCH</span><h2>${esc(item[0])}</h2><div class="strategy-count-chip"><strong>${Number(item[1])}</strong></div></article>`).join('');
    $('#researchEmpty').classList.toggle('hidden', data.reports.length > 0);
    $('#researchReports').innerHTML = data.reports.map(item => { const actions = (reportActions[item.status] || []).map(action => `<button class="primary-button" data-report-action="${esc(action[0])}" data-report-id="${esc(item.report_id)}">${esc(action[1])}</button>`).join(''); return `<article class="strategy-card"><span class="strategy-version">v${Number(item.version)}</span><h2>${esc(item.subject)}</h2><p>${esc(item.provider_id || '尚未调用')} · ${esc(item.model_id || '')}</p><div class="strategy-card-footer"><span>${esc(item.status)}</span><span>${esc(item.created_at)}</span></div><div class="topbar-actions">${actions}</div></article>`; }).join('');
  }

  async function loadIntegrations() {
    const response = await fetch('/api/integrations'); const data = await responseJson(response, '集成状态载入失败');
    $('#integrationGrid').innerHTML = data.components.map(item => `<article class="strategy-card"><span class="strategy-version">${esc(item.detail)}</span><h2>${esc(item.component)}</h2><div class="strategy-card-footer"><span>${esc(item.status)}</span></div></article>`).join('');
  }

  async function loadArtifacts(pageId) {
    const page = $(`#page-${pageId}`); const grid = $('.artifact-grid', page); const type = grid.dataset.artifactType;
    const response = await fetch(`/api/artifacts?type=${encodeURIComponent(type)}`); const data = await responseJson(response, '平台产物载入失败');
    const items = data.artifacts || [];
    grid.innerHTML = items.length ? items.map(item => `<article class="strategy-card"><span class="strategy-version">${esc(item.artifact_type)} · v${Number(item.version)}</span><h2>${esc(item.artifact_id)}</h2><p>${esc(item.strategy_id || '平台级')} · ${esc(item.release_id || '未关联发布')}</p><div class="strategy-card-footer"><span>${esc(item.status)}</span><span>${esc(item.created_at)}</span></div></article>`).join('') : `<div class="empty-state panel"><h3>暂无${esc(type)}产物</h3><p>确定性引擎写入版本化产物后会出现在这里。</p></div>`;
  }

  function mutationHeaders() {
    const token = window.sessionStorage.getItem('platformApiToken') || '';
    return {'Content-Type':'application/json', ...(token ? {'X-Platform-Token':token} : {})};
  }

  async function postMutation(url, body) {
    let response = await fetch(url, {method:'POST', headers:mutationHeaders(), body:JSON.stringify(body)});
    if (response.status === 403) {
      const token = window.prompt('请输入平台变更 Token（仅保存在当前浏览器会话）');
      if (!token) throw new Error('已取消鉴权');
      window.sessionStorage.setItem('platformApiToken', token);
      response = await fetch(url, {method:'POST', headers:mutationHeaders(), body:JSON.stringify(body)});
    }
    const data = await responseJson(response, '操作失败');
    return data;
  }

  function closeSidebar() {
    $('#sidebar').classList.remove('open');
    $('#scrim').classList.remove('open');
  }

  async function init() {
    ready = true;
    await loadHealth();
    window.setInterval(loadHealth, 30000);
    $('#menuButton').addEventListener('click', () => { $('#sidebar').classList.add('open'); $('#scrim').classList.add('open'); });
    $('#scrim').addEventListener('click', closeSidebar);
    document.addEventListener('click', async event => {
      const shellPage = event.target.closest('[data-shell-page]');
      if (shellPage) {
        try { shellPage.dataset.shellPage === 'home' ? openHome() : await openShellPage(shellPage.dataset.shellPage); }
        catch (error) { showError(error); }
        return;
      }
      const strategy = event.target.closest('[data-open-strategy]');
      if (strategy) {
        try { await openStrategy(strategy.dataset.openStrategy); }
        catch (error) { showError(error); }
        return;
      }
      const reportAction = event.target.closest('[data-report-action]');
      if (reportAction) {
        try { await postMutation(`/api/ai-research/reports/${encodeURIComponent(reportAction.dataset.reportId)}/${encodeURIComponent(reportAction.dataset.reportAction)}`, {actor:'web-reviewer', note:'Web 控制台操作'}); await loadResearch(); }
        catch (error) { showError(error); }
        return;
      }
      const releaseAction = event.target.closest('[data-release-action]');
      if (releaseAction) {
        const actor = window.prompt('请输入已授权审批人标识'); if (!actor) return;
        try { await postMutation(`/api/governance/releases/${encodeURIComponent(releaseAction.dataset.releaseId)}/${encodeURIComponent(releaseAction.dataset.releaseAction)}`, {actor, note:'Web 控制台操作'}); await loadSignalGovernance(); }
        catch (error) { showError(error); }
      }
    });
    try { await loadCatalog(); }
    catch (error) {
      $('#strategyEmpty').classList.remove('hidden');
      $('#strategyEmpty').querySelector('h3').textContent = '策略目录载入失败';
      $('#strategyEmpty').querySelector('p').textContent = error.message;
    }
    openHome();
  }

  document.addEventListener('DOMContentLoaded', init);
  return { register, openHome, openStrategy };
})();

window.StrategyConsole = StrategyConsole;
