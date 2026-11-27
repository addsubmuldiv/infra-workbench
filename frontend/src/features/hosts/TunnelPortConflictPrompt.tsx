import {useRef,useState} from 'react';
import {AppConfirm} from '../../shared/AppConfirm';
import {t,useLocale} from '../../shared/i18n';
import {tunnelRequest,type TunnelRule} from './SSHTunnelPanel';

type Host={id:string;target:string;alias?:string;ssh_tunnels?:TunnelRule[]};

export function TunnelPortConflictPrompt({hosts,notice}:{hosts:Host[];notice:(message:string)=>void}){
  useLocale();
  const handled=useRef(new Set<string>());
  const [submitting,setSubmitting]=useState(false);
  if(submitting)return null;

  for(const host of hosts){
    for(const rule of host.ssh_tunnels??[]){
      const conflict=rule.port_conflict;
      if(!conflict||handled.current.has(conflict.confirmation))continue;
      const {confirmation,process,addresses}=conflict;
      const machine=host.alias?`${host.alias} (${host.target})`:host.target;
      const listeners=addresses.join(', ');
      async function decide(accepted:boolean){
        if(handled.current.has(confirmation))return;
        handled.current.add(confirmation);
        setSubmitting(true);
        try{
          const decision=accepted?'release':'dismiss';
          const path=`/${encodeURIComponent(rule.id)}/port-conflict/${decision}`;
          const result=await tunnelRequest(host.id,path,'POST',{confirmation});
          switch(result.status){
            case 'changed':
              notice(t('远端监听进程或隧道配置已变化。请重新连接隧道。',
                'The remote listener or tunnel configuration changed. Reconnect the tunnel to check again.'));
              break;
            case 'still_occupied':
              notice(t('已发送 SIGTERM，远端端口仍被占用。','SIGTERM was sent. The remote port is still occupied.'));
              break;
            case 'unverified':
              notice(t('当前 SSH 账号无法结束该进程。','This SSH account could not terminate the process.'));
              break;
          }
        }catch(error){
          notice(error instanceof Error?error.message:String(error));
        }finally{
          setSubmitting(false);
        }
      }
      return <AppConfirm key={confirmation}
        heading={t('远端端口被占用','Remote port is in use')}
        message={t(
          `隧道「${rule.name}」需要使用 ${machine} 上的 ${listeners}。进程 ${process.name}（PID ${process.pid}，UID ${process.uid}）正在监听。结束它可能会中断它的其他连接。`,
          `The tunnel “${rule.name}” needs ${listeners} on ${machine}. ${process.name} (PID ${process.pid}, UID ${process.uid}) is listening there. Stopping it may interrupt its other connections.`)}
        confirmLabel={t('结束进程并重连','Stop process and reconnect')}
        cancelLabel={t('保留进程','Keep process')}
        finish={accepted=>void decide(accepted)}/>;
    }
  }
  return null;
}
