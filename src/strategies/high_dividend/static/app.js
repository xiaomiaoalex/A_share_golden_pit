window.StrategyConsole.register({
  id: 'high-dividend',
  mount() {},
  activate(strategy) {
    document.getElementById('pageTitle').textContent = strategy.short_name;
  },
  navigate() {
    document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
    document.getElementById('page-high-dividend').classList.add('active');
  },
  deactivate() {}
});
