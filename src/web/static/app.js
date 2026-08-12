const StrategyConsole = (() => {
  const modules = new Map();
  const loadedScripts = new Set();
  let ready = false;
  let activeStrategy = null;
  let catalog = [];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  const statusLabels = {ACTIVE:'运行中', BETA:'试运行', PAUSED:'已暂停', RUNNING:'运行中', FINISHED:'已完成', FINISHED_WITH_ERRORS:'完成但有异常', INTERRUPTED:'已中断'};

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
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '策略目录载入失败');
    catalog = data.strategies || [];
    $('#strategyCount').textContent = catalog.length;
    $('#strategyNavCount').textContent = catalog.length;
    renderCatalog();
    await Promise.all(catalog.map(loadUiModule));
  }

  function loadUiModule(strategy) {
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
    $('#pageTitle').textContent = '策略总览';
    closeSidebar();
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  function closeSidebar() {
    $('#sidebar').classList.remove('open');
    $('#scrim').classList.remove('open');
  }

  async function init() {
    ready = true;
    modules.forEach(mount);
    $('#menuButton').addEventListener('click', () => { $('#sidebar').classList.add('open'); $('#scrim').classList.add('open'); });
    $('#scrim').addEventListener('click', closeSidebar);
    document.addEventListener('click', async event => {
      const home = event.target.closest('[data-shell-page="home"]');
      if (home) { openHome(); return; }
      const strategy = event.target.closest('[data-open-strategy]');
      if (strategy) {
        try { await openStrategy(strategy.dataset.openStrategy); }
        catch (error) { window.alert(error.message); }
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
