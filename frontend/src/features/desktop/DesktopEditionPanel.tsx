import {useEffect,useState} from 'react';
import {useAppConfirm} from '../../shared/AppConfirm';
import {t} from '../../shared/i18n';
import {workspaceStorage} from '../../workspace/workspaceState';
import {isDemo} from '../onboarding/demoBootstrap';
import {RELEASES_URL} from './desktopUpdates';
import {canSwitchEdition} from './useEditionSwitchGuard';

type EditionStatus={current:'installed'|'development';switch_supported:boolean;switch_available:boolean};
type EditionCommand='desktop_edition_status'|'desktop_switch_edition';
type DesktopTarget=Window&{__TAURI_INTERNALS__?:{invoke:(command:EditionCommand)=>Promise<unknown>}};
const native=isDemo?undefined:(window as DesktopTarget).__TAURI_INTERNALS__;

function switchError(error:unknown){
  const message=error instanceof Error?error.message:String(error);
  switch(message){
    case 'desktop_switch_unsaved':
    case 'update_shutdown_terminals':
      return t('请先保存所有桌面窗口的修改并关闭活动终端，再切换版本。','Save changes in all desktop windows and close active terminals before switching.');
    case 'update_shutdown_transfers':
      return t('请等待文件传输结束后再切换版本。','Wait for file transfers to finish before switching.');
    case 'update_shutdown_busy':
    case 'desktop_switch_busy':
      return t('请等待正在进行的任务结束后再切换版本。','Wait for active operations to finish before switching.');
    case 'update_shutdown_identity':
      return t('当前后台与桌面程序不匹配。请保存工作，从托盘退出后，重新打开当前版本再试。','The running service does not match the desktop app. Save your work, quit from the tray, then reopen this edition and try again.');
    case 'desktop_switch_window_unresponsive':
      return t('无法确认所有桌面窗口的状态。请保存并关闭其他窗口后重试。','Could not confirm every desktop window is ready. Save your work, close the other windows, and try again.');
    case 'desktop_switch_target_missing':
      return t('找不到另一版本的程序。请重新打开此页检查。','The other edition could not be found. Reopen this page to check again.');
    case 'desktop_switch_shutdown_timeout':
      return t('后台未能及时退出，切换已取消。请稍后重新打开工作台。','The service did not exit in time. Switching was cancelled. Reopen the workbench in a moment.');
    default:
      return t('未能切换版本。请确认两个版本均可正常启动后重试。','Could not switch editions. Check that both editions can start and try again.');
  }
}

export function DesktopEditionPanel(){
  const [status,setStatus]=useState<EditionStatus|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const {confirm,confirmation}=useAppConfirm();

  useEffect(()=>{
    if(!native)return;
    let active=true;
    const refresh=()=>void native.invoke('desktop_edition_status').then(value=>{
      if(active)setStatus(value as EditionStatus);
    }).catch(()=>{});
    refresh();
    window.addEventListener('focus',refresh);
    return()=>{active=false;window.removeEventListener('focus',refresh)};
  },[]);
  if(!native||!status)return null;

  const installed=status.current==='installed';
  const action=installed?t('切换到开发版','Switch to development edition'):t('切换到安装版','Switch to installed edition');
  const switchEdition=async()=>{
    if(!canSwitchEdition(window,()=>workspaceStorage.hasUnsaved())){
      setError(switchError('desktop_switch_unsaved'));
      return;
    }
    const accepted=await confirm(t('应用将关闭当前桌面窗口和后台，再打开另一版本。两版默认使用各自的数据目录。','The desktop windows and local service will close before the other edition opens. Each edition uses its own data directory by default.'));
    if(!accepted)return;
    setBusy(true);setError('');
    try{await native.invoke('desktop_switch_edition')}
    catch(failure){setError(switchError(failure));setBusy(false)}
  };
  return <section className="settings-page" aria-labelledby="desktop-edition-title">
    <div className="settings-section-title"><h2 id="desktop-edition-title">{t('运行版本','Running edition')}</h2></div>
    <div className="settings-card">
      <p>{installed?t('当前使用安装版','You are using the installed edition'):t('当前使用开发版（源码）','You are using the development edition (source checkout)')}</p>
      {status.switch_supported&&<>
        {installed||status.switch_available
          ?<button type="button" className="secondary" disabled={busy||!status.switch_available} onClick={()=>void switchEdition()}>
            {busy?t('正在切换…','Switching…'):action}
          </button>
          :<a href={RELEASES_URL+'/latest'} target="_blank" rel="noreferrer">{t('下载安装版','Download the installed edition')}</a>}
        {installed&&!status.switch_available&&<p className="settings-help">{t('构建并启动一次开发版后，即可从这里切换。','Build and open the development edition once to switch to it here.')}</p>}
      </>}
      {error&&<p role="alert" className="connection-error">{error}</p>}
    </div>
    {confirmation}
  </section>;
}
