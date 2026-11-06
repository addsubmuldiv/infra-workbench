import {useEffect,useSyncExternalStore} from 'react';
import {t,useLocale} from './i18n';
import {isDemo} from './demoBootstrap';
import {workspaceStorage} from './workspaceState';
import {canRestartForUpdate,createDesktopUpdater,nativeUpdateBridge,RELEASES_URL} from './desktopUpdates';
import './desktopUpdates.css';
declare const __IWB_VERSION__:string;
const currentVersion=typeof __IWB_VERSION__==='undefined'?'':__IWB_VERSION__;
const updater=createDesktopUpdater(nativeUpdateBridge(typeof window==='undefined'?null:window,isDemo),()=>canRestartForUpdate(window,()=>workspaceStorage.hasUnsaved()));
if(!isDemo&&nativeUpdateBridge(window)){
  const target=window as unknown as {__IWB_DESKTOP_UPDATE_SAFETY__?:(freeze:boolean)=>{safe:boolean;reason?:string};__IWB_DESKTOP_UPDATE_FREEZE__?:(frozen:boolean)=>void};
  target.__IWB_DESKTOP_UPDATE_SAFETY__=freeze=>{target.__IWB_DESKTOP_UPDATE_FREEZE__?.(freeze);return {safe:canRestartForUpdate(window,()=>workspaceStorage.hasUnsaved()),reason:t('请先保存修改并关闭活动终端。','Save changes and close active terminals first.')}};
  target.__IWB_DESKTOP_UPDATE_FREEZE__=frozen=>{
    document.getElementById('desktop-update-freeze')?.remove();
    const root=document.getElementById('root');if(root)root.inert=frozen;
    if(!frozen)return;
    const overlay=document.createElement('div');overlay.id='desktop-update-freeze';overlay.className='desktop-update-freeze';overlay.setAttribute('role','status');overlay.textContent=t('正在准备安装更新，请完成桌面确认窗口中的操作…','Preparing the update. Complete the desktop confirmation prompt…');document.body.append(overlay);
  };
}
function useUpdates(){useLocale();return useSyncExternalStore(updater.subscribe,updater.getSnapshot)}
function errorText(error:string){
  if(error==='restart_blocked')return t('请先保存未完成的修改并关闭活动终端，再安装更新。','Save pending changes and close active terminals before installing.');
  if(error==='update_shutdown_busy')return t('后台仍有操作正在进行。请等助手任务、远程命令或导入结束后，再点击安装。','The background service is still busy. Wait for assistant tasks, remote commands, or imports to finish, then install again.');
  if(error==='update_shutdown_terminals')return t('请关闭所有工作台窗口中的活动终端，再点击安装。','Close active terminals in all workbench windows, then install again.');
  if(error==='update_shutdown_transfers')return t('请等待文件传输结束，再点击安装。','Wait for file transfers to finish, then install again.');
  if(error==='update_shutdown_identity')return t('当前后台实例与更新请求不匹配。请保存工作，从托盘退出后重新打开应用，再安装更新。','The running background service does not match the update request. Save your work, quit from the tray, and reopen the app before installing.');
  if(error==='update_force_timeout')return t('强制退出后，后台进程或服务端口仍未释放，安装尚未启动。','The background process or service port is still active after force quit. Installation has not started.');
  if(error.startsWith('update_shutdown_failed')||error.includes('后台拒绝更新退出'))return t('本机后台拒绝退出，安装程序尚未启动。请保存工作，确认后台操作结束后重试。','The local background service refused to exit. The installer has not started. Save your work and retry when background operations have finished.');
  if(/404|not found|private|public.*feed/i.test(error))return t('暂时无法读取公开更新源。仓库可能尚未公开或尚未发布更新，请稍后重试。','The public update feed is unavailable. The repository or release may not be public yet. Please retry later.');
  return t('更新操作未完成。详情：','Update could not complete. Details: ')+error;
}
export function DesktopUpdateNotification({openSettings}:{openSettings:()=>void}){
  const status=useUpdates();
  useEffect(()=>{if(!isDemo)updater.start()},[]);
  useEffect(()=>{if(!['checking','downloading','installing'].includes(status.phase))return;const timer=window.setInterval(()=>void updater.run('status'),1000);return()=>clearInterval(timer)},[status.phase]);
  if(isDemo||!status.supported||!['available','downloaded'].includes(status.phase))return null;
  return <aside className="desktop-update-notice" role="status"><span>{status.phase==='downloaded'?t('更新已下载，可安装并重启。','Update downloaded. Ready to install and restart.'):t('发现新版本：','New version available: ')+status.available_version}</span><button onClick={()=>{
    try{localStorage.setItem('iwb.settings.navigation',JSON.stringify({category:'about',ai:'models',integrations:'mcp'}))}catch{/* Optional navigation preference. */}
    window.dispatchEvent(new Event('iwb:show-update-settings'));
    openSettings();
  }}>{t('查看更新','View update')}</button></aside>;
}
export function DesktopUpdates(){
  const status=useUpdates();
  const busy=['checking','downloading','installing'].includes(status.phase);
  const ready=!!status.available_version;
  const downloaded=status.phase==='downloaded';
  const label={idle:t('尚未检查更新','Not checked yet'),checking:t('正在检查更新…','Checking for updates…'),available:t('有新版本可用','Update available'),downloading:t('正在下载…','Downloading…'),downloaded:t('下载完成','Download complete'),installing:t('正在准备安装…','Preparing installation…'),error:t('更新操作未完成','Update could not complete')}[status.phase];
  return <section className="settings-page desktop-updates"><div className="settings-section-title"><div><h2>{t('桌面应用更新','Desktop app updates')}</h2><p>{t('启动时检查更新；下载与安装均由你决定。','Checks at startup. You choose when to download and install.')}</p></div></div><div className="settings-card">
    {isDemo?<p>{t('演示中不检查、下载或安装更新。','Updates are disabled in the demo.')}</p>:!status.supported?<p>{t('当前运行方式不支持应用内更新。浏览器、源码、调试版和旧桌面版请到官方发布页面手动安装支持更新的桌面版本（0.1.1 或更高版本）。','In-app updates are unavailable in this runtime. For browser, source, debug or older desktop builds, manually install a desktop release with updater support (0.1.1 or later) from the official releases page.')}</p>:<>
      <p>{t('当前版本：','Current version: ')}{status.current_version||currentVersion||t('正在读取','Loading')}{ready&&<> · {t('可用版本：','Available version: ')}{status.available_version}</>}</p>
      <p role="status">{status.phase==='idle'&&status.last_checked?t('已是最新版本','Up to date'):label}</p>
      {status.phase==='downloading'&&<><progress aria-label={t('更新下载进度','Update download progress')} value={status.total_bytes?status.downloaded_bytes:undefined} max={status.total_bytes||undefined}/><p>{(status.downloaded_bytes/1024/1024).toFixed(1)} MB{status.total_bytes?` / ${(status.total_bytes/1024/1024).toFixed(1)} MB`:''}</p></>}
      {status.notes&&<details open><summary>{t('版本说明','Release notes')}</summary><pre className="desktop-update-notes">{status.notes}</pre></details>}
      {status.error&&<p role="alert" className="connection-error">{errorText(status.error)}</p>}
      <div className="desktop-update-actions"><button disabled={busy} onClick={()=>void updater.run('check')}>{t('检查更新','Check for updates')}</button>{ready&&<button className="primary" disabled={busy} onClick={()=>void updater.run(downloaded?'install':'download')}>{downloaded?t('安装并重启…','Install and restart…'):t('下载更新','Download update')}</button>}</div>
      <p className="subtle">{t('安装前会请求确认。请先保存修改并关闭活动终端；更新保留本地机器、凭据和设置。','You will be asked to confirm installation. Save changes and close active terminals first. Local machines, credentials and settings are preserved.')}</p>
    </>}{!isDemo&&<a href={RELEASES_URL} target="_blank" rel="noreferrer">{t('官方发布页面','Official releases')}</a>}
  </div></section>;
}
