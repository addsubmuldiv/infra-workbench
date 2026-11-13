// Shared by the packaged bootstrap and the origin-guarded native initialization script.
(function startup() {
  const service = location.origin === 'http://127.0.0.1:8765';
  const bootstrap = (location.protocol === 'tauri:' && location.hostname === 'localhost') || ['tauri://localhost', 'http://tauri.localhost', 'https://tauri.localhost'].includes(location.origin);
  if ((!service && !bootstrap) || window.__iwbStartup) return;
  // Tauri runs initialization scripts before HTML parsing. Wait for the
  // document's blocking stylesheet; never present an unstyled startup overlay.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startup, {once:true});return;
  }
  if (!document.documentElement) {
    const observer = new MutationObserver(() => {
      if (document.documentElement) {observer.disconnect();startup();}
    });
    observer.observe(document, {childList:true});return;
  }
  // Service locale is owned by the shared workspace; its default is Chinese.
  let en = service ? (document.documentElement.lang || 'zh').toLowerCase().startsWith('en') : !navigator.language.toLowerCase().startsWith('zh');
  const messages = {en: {
    connecting:'Connecting to local service…', backend:'Starting local service…', waiting:'Waiting for local service to respond…',
    health:'Local service ready', frontend:'Loading workspace…', error:'Unable to open the workspace',
    retry:'Try again', minimize:'Minimize window', maximize:'Maximize window', restore:'Restore window', close:'Close window', hint:'Closing this window keeps your workspace running. To quit, use the system tray or menu bar.',
    progress:'Startup stages', note:'Progress follows completed stages; it is not a time estimate.', failedNote:'Loading has stopped. Resolve the error and try again.', elapsed:'Elapsed', slow:'This is taking longer than usual. You can close this window and open it again later.'
  }, zh: {
    connecting:'正在连接本地后台…', backend:'正在启动本地后台…', waiting:'正在等待本地后台恢复响应…',
    health:'本地后台已就绪', frontend:'正在加载工作台…', error:'暂时无法打开工作台',
    retry:'重新连接', minimize:'最小化窗口', maximize:'最大化窗口', restore:'还原窗口', close:'关闭窗口', hint:'关闭窗口后，工作台会保留在后台。彻底退出请使用系统托盘或菜单栏。',
    progress:'启动阶段进度', note:'百分比按已完成的启动阶段更新，不代表剩余时间。', failedNote:'加载已停止，请处理错误后重新连接。', elapsed:'已等待', slow:'本次启动用时较长。可以先关闭窗口，稍后重新打开。'
  }};
  let copy = messages[en ? 'en' : 'zh'];
  let lastStage = service ? 'frontend' : 'connecting';
  let lastError = '';
  const layer = document.createElement('div'); layer.id = 'iwb-startup';
  layer.innerHTML = `<div class="iwb-startup-preview" aria-hidden="true"><div class="iwb-startup-sidebar"><div class="iwb-startup-line"></div><div class="iwb-startup-line iwb-startup-short"></div><div class="iwb-startup-line"></div><div class="iwb-startup-line"></div><div class="iwb-startup-line iwb-startup-short"></div></div><div class="iwb-startup-cards">${Array.from({length:4},()=>'<div class="iwb-startup-card"><div class="iwb-startup-line iwb-startup-short"></div><div class="iwb-startup-line"></div><div class="iwb-startup-line"></div></div>').join('')}</div></div>
  <main id="iwb-startup-panel" aria-busy="true"><div class="iwb-startup-brand"><svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 32 32" aria-hidden="true"><rect x="1" y="1" width="30" height="30" rx="8" fill="#152c39"/><g fill="none" stroke="#e9fff9" stroke-width="2" stroke-linecap="round"><rect x="8" y="8" width="16" height="16" rx="3"/><path d="M12 5v3m8-3v3M5 12h3m-3 8h3m16-8h3m-3 8h3M12 24v3m8-3v3"/></g><rect x="12" y="12" width="8" height="8" rx="1.5" fill="#70e2c3"/><circle cx="25" cy="25" r="5" fill="#152c39"/><circle cx="25" cy="25" r="3.5" fill="#70e2c3"/></svg><h1>Infra Workbench</h1></div>
  <div class="iwb-startup-status-row"><span class="iwb-startup-spinner" aria-hidden="true"></span><p id="iwb-startup-status" role="status" aria-live="polite"></p></div><div class="iwb-startup-track" id="iwb-startup-progress" role="progressbar" aria-label="${copy.progress}" aria-valuemin="0" aria-valuemax="100"><div id="iwb-startup-bar"></div></div><div class="iwb-startup-meta"><span id="iwb-startup-percent"></span><span id="iwb-startup-elapsed"></span></div><p class="iwb-startup-note" id="iwb-startup-note">${copy.note}</p><p class="iwb-startup-note" id="iwb-startup-slow" hidden>${copy.slow}</p><button id="iwb-startup-retry" hidden>${copy.retry}</button><p class="iwb-startup-note" id="iwb-startup-hint">${copy.hint}</p></main>`;
  document.documentElement.appendChild(layer);
  if (bootstrap && window.__iwbDesktopTitlebar) {
    const controls = document.createElement('div');
    controls.className = 'iwb-startup-window';
    const drag = document.createElement('div');
    drag.className = 'iwb-startup-drag';
    const invoke = action => window.__TAURI_INTERNALS__.invoke('main_window_action', {action});
    const addButton = (symbol, label, action) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = symbol;
      button.title = label;
      button.setAttribute('aria-label', label);
      button.addEventListener('click', action);
      controls.appendChild(button);
      return button;
    };
    controls.appendChild(drag);
    addButton('−', copy.minimize, () => invoke('minimize').catch(() => {}));
    const maximize = addButton('□', copy.maximize, toggleMaximize);
    addButton('×', copy.close, () => invoke('close').catch(() => {}));
    function updateMaximized(value) {
      maximize.textContent = value ? '❐' : '□';
      maximize.title = value ? copy.restore : copy.maximize;
      maximize.setAttribute('aria-label', maximize.title);
    }
    function toggleMaximize() {
      invoke('toggle-maximize').then(updateMaximized).catch(() => {});
    }
    invoke('status').then(updateMaximized).catch(() => {});
    drag.addEventListener('mousedown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      if (event.detail === 2) toggleMaximize();
      else invoke('drag').catch(() => {});
    });
    layer.prepend(controls);
  }
  const get = id => document.getElementById(`iwb-startup-${id}`);
  const started = performance.now();
  let stoppedAt = null;
  let progress = service ? 85 : 5;
  const timer = setInterval(tick, 1000);
  const timeout = service ? setTimeout(() => update('error', progress, '工作台未能完成加载，请重新连接。'), 60000) : null;
  function tick() {
    const seconds = Math.floor(((stoppedAt ?? performance.now()) - started) / 1000);
    get('elapsed').textContent = `${copy.elapsed} ${seconds}${en ? ' s' : ' 秒'}`;
    get('slow').hidden = lastStage === 'error' || seconds < 15;
  }
  function update(stage, percent = progress, error = '') {
    lastStage = stage;lastError = error;
    if (stage === 'error' && stoppedAt === null) {
      stoppedAt = performance.now();clearInterval(timer);
      if (timeout !== null) clearTimeout(timeout);
      tick();
    }
    progress = Math.max(progress, percent);
    const englishErrors = [
      ['工作台未能完成加载', 'The workspace did not finish loading. Please try again.'],
      ['后台未能在 60 秒内就绪', 'The local service did not become ready within 60 seconds. See desktop.log.'],
      ['后台启动失败', 'The local service failed to start. See desktop.log.'],
      ['8765 端口', 'Port 8765 is occupied or failed the workbench health check. No processes were stopped.'],
      ['本地后台响应超时', 'The local service timed out. Check the system tray or menu bar. No duplicate service was started.'],
      ['无法连接本地后台端口', 'The local connection could not be confirmed. No processes were stopped. See startup.log.'],
      ['无法查询本地后台端口', 'The Windows listener state could not be queried. No processes were stopped. See startup.log.'],
      ['本地端口', 'The local port failed the workbench health check. No processes were stopped.'],
      ['找不到项目 Python 环境', 'The project Python environment is missing. Run the existing installer first.'],
      ['安装包缺少 Python 后台', 'The Python service is missing from this installation. Reinstall the complete desktop app.'],
      ['无法确定当前用户的数据目录', 'The user data directory could not be determined.'],
      ['无法创建数据目录', 'The data directory could not be created.'],
      ['无法启动后台', 'The local service could not be started.']
    ];
    const detail = en ? (englishErrors.find(([prefix]) => error.includes(prefix))?.[1] || error) : error;
    get('status').textContent = error ? `${copy.error} · ${detail}` : (copy[stage] || stage);
    get('panel').setAttribute('aria-busy', stage === 'error' ? 'false' : 'true');
    get('retry').hidden = stage !== 'error';
    get('note').textContent = stage === 'error' ? copy.failedNote : copy.note;
    get('percent').textContent = `${progress}%`;
    get('bar').style.width = `${progress}%`;
    get('progress').setAttribute('aria-valuenow', String(progress));
  }
  const localeObserver = service ? new MutationObserver(() => {
    en = (document.documentElement.lang || 'zh').toLowerCase().startsWith('en');
    copy = messages[en ? 'en' : 'zh'];
    get('retry').textContent = copy.retry;
    get('hint').textContent = copy.hint;
    get('note').textContent = copy.note;
    get('slow').textContent = copy.slow;
    get('progress').setAttribute('aria-label', copy.progress);
    update(lastStage, progress, lastError);tick();
  }) : null;
  localeObserver?.observe(document.documentElement, {attributes:true, attributeFilter:['lang']});
  get('retry').addEventListener('click', () => location.reload());
  window.__iwbStartup = {update, finish() {localeObserver?.disconnect();clearInterval(timer);if (timeout !== null) clearTimeout(timeout);layer.remove();}};
  update(service ? 'frontend' : 'connecting');tick();
})();
