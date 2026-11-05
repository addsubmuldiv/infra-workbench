// Shared by the packaged bootstrap and the origin-guarded native initialization script.
(function startup() {
  const service = location.origin === 'http://127.0.0.1:8765';
  const bootstrap = (location.protocol === 'tauri:' && location.hostname === 'localhost') || ['tauri://localhost', 'http://tauri.localhost', 'https://tauri.localhost'].includes(location.origin);
  if ((!service && !bootstrap) || window.__iwbStartup) return;
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
    retry:'Try again', hint:'Closing this window keeps your workspace running. To quit, use the system tray or menu bar.',
    progress:'Startup stages', note:'Progress follows completed stages; it is not a time estimate.', elapsed:'Elapsed', slow:'This is taking longer than usual. You can close this window and open it again later.'
  }, zh: {
    connecting:'正在连接本地后台…', backend:'正在启动本地后台…', waiting:'正在等待本地后台恢复响应…',
    health:'本地后台已就绪', frontend:'正在加载工作台…', error:'暂时无法打开工作台',
    retry:'重新连接', hint:'关闭窗口后，工作台会保留在后台。彻底退出请使用系统托盘或菜单栏。',
    progress:'启动阶段进度', note:'百分比按已完成的启动阶段更新，不代表剩余时间。', elapsed:'已等待', slow:'本次启动用时较长。可以先关闭窗口，稍后重新打开。'
  }};
  let copy = messages[en ? 'en' : 'zh'];
  let lastStage = service ? 'frontend' : 'connecting';
  let lastError = '';
  const layer = document.createElement('div'); layer.id = 'iwb-startup';
  layer.innerHTML = `<style>
  #iwb-startup{position:fixed;inset:0;z-index:2147483646;background:#f2f5f9;color:#25414b;font:14px system-ui,sans-serif;display:grid;place-items:center;overflow:hidden}
  #iwb-startup *{box-sizing:border-box}#iwb-startup .preview{position:absolute;inset:0;display:grid;grid-template-columns:210px 1fr;gap:22px;padding:25px;filter:blur(5px);opacity:.5;pointer-events:none}
  #iwb-startup .sidebar,#iwb-startup .card{background:#fff;border:1px solid #dbe5e9;border-radius:12px;padding:22px}#iwb-startup .line{height:12px;background:#d3dfe6;border-radius:6px;margin:18px 0;width:72%}#iwb-startup .line.short{width:45%}#iwb-startup .cards{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-content:start;padding-top:70px}#iwb-startup .card{height:180px}
  #iwb-startup-panel{position:relative;width:min(460px,calc(100% - 40px));padding:32px;border:1px solid #d8e4e9;border-radius:18px;background:rgba(255,255,255,.96);box-shadow:0 16px 60px #263c4d14}
  #iwb-startup .brand{display:flex;align-items:center;gap:14px;margin-bottom:27px}#iwb-startup svg{width:48px;height:48px;flex:none}#iwb-startup h1{font-size:23px;margin:0;letter-spacing:-.5px}#iwb-startup-status{font-size:16px;margin:0;line-height:1.6;overflow-wrap:anywhere}#iwb-startup .status-row{display:flex;gap:11px;align-items:center}
  #iwb-startup .spinner{width:17px;height:17px;border:2px solid #d5e8e5;border-top-color:#187f72;border-radius:50%;animation:iwb-spin 1s linear infinite;flex:none}#iwb-startup-panel[aria-busy=false] .spinner{display:none}
  #iwb-startup .track{height:6px;background:#e6edef;border-radius:4px;margin-top:23px;overflow:hidden}#iwb-startup-bar{height:100%;background:#258b7f;width:5%}#iwb-startup .meta{display:flex;justify-content:space-between;gap:14px;margin-top:10px;color:#58717d;font-size:12px}#iwb-startup .note{font-size:12px;color:#71848e;line-height:1.7;margin:14px 0 0}#iwb-startup-hint{border-top:1px solid #e7edef;padding-top:18px}#iwb-startup-slow{color:#8a6630}
  #iwb-startup-retry{margin-top:18px;background:#187f72;color:white;border:0;border-radius:7px;padding:10px 18px;font:inherit;cursor:pointer}#iwb-startup-retry:focus-visible{outline:3px solid #7cbcaf;outline-offset:3px}#iwb-startup [hidden]{display:none!important}
  @keyframes iwb-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){#iwb-startup .spinner{animation:none;border-top-color:#187f72;border-right-color:#187f72}}@media(max-width:580px){#iwb-startup .preview{grid-template-columns:100px 1fr}#iwb-startup .cards{grid-template-columns:1fr}#iwb-startup-panel{padding:25px}}
  </style><div class="preview" aria-hidden="true"><div class="sidebar"><div class="line"></div><div class="line short"></div><div class="line"></div><div class="line"></div><div class="line short"></div></div><div class="cards">${Array.from({length:4},()=>'<div class="card"><div class="line short"></div><div class="line"></div><div class="line"></div></div>').join('')}</div></div>
  <main id="iwb-startup-panel" aria-busy="true"><div class="brand"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true"><rect x="1" y="1" width="30" height="30" rx="8" fill="#152c39"/><g fill="none" stroke="#e9fff9" stroke-width="2" stroke-linecap="round"><rect x="8" y="8" width="16" height="16" rx="3"/><path d="M12 5v3m8-3v3M5 12h3m-3 8h3m16-8h3m-3 8h3M12 24v3m8-3v3"/></g><rect x="12" y="12" width="8" height="8" rx="1.5" fill="#70e2c3"/><circle cx="25" cy="25" r="5" fill="#152c39"/><circle cx="25" cy="25" r="3.5" fill="#70e2c3"/></svg><h1>Infra Workbench</h1></div>
  <div class="status-row"><span class="spinner" aria-hidden="true"></span><p id="iwb-startup-status" role="status" aria-live="polite"></p></div><div class="track" id="iwb-startup-progress" role="progressbar" aria-label="${copy.progress}" aria-valuemin="0" aria-valuemax="100"><div id="iwb-startup-bar"></div></div><div class="meta"><span id="iwb-startup-percent"></span><span id="iwb-startup-elapsed"></span></div><p class="note" id="iwb-startup-note">${copy.note}</p><p class="note" id="iwb-startup-slow" hidden>${copy.slow}</p><button id="iwb-startup-retry" hidden>${copy.retry}</button><p class="note" id="iwb-startup-hint">${copy.hint}</p></main>`;
  document.documentElement.appendChild(layer);
  const get = id => document.getElementById(`iwb-startup-${id}`);
  const started = performance.now();
  let progress = service ? 85 : 5;
  const timer = setInterval(tick, 1000);
  const timeout = service ? setTimeout(() => update('error', progress, '工作台未能完成加载，请重新连接。'), 60000) : null;
  function tick() {
    const seconds = Math.floor((performance.now() - started) / 1000);
    get('elapsed').textContent = `${copy.elapsed} ${seconds}${en ? ' s' : ' 秒'}`;
    get('slow').hidden = seconds < 15;
  }
  function update(stage, percent = progress, error = '') {
    lastStage = stage;lastError = error;
    progress = Math.max(progress, percent);
    const englishErrors = [
      ['工作台未能完成加载', 'The workspace did not finish loading. Please try again.'],
      ['后台未能在 60 秒内就绪', 'The local service did not become ready within 60 seconds. See desktop.log.'],
      ['后台启动失败', 'The local service failed to start. See desktop.log.'],
      ['8765 端口', 'Port 8765 is occupied or failed the workbench health check. No processes were stopped.'],
      ['本地后台响应超时', 'The local service timed out. Check the system tray or menu bar. No duplicate service was started.'],
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
