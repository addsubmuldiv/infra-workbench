import {useRef,useState} from 'react';
import {AppConfirm} from '../../shared/AppConfirm';
import {t,useLocale} from '../../shared/i18n';
import {tunnelRequest,type TunnelRule} from './SSHTunnelPanel';

type Host={id:string;target:string;alias?:string;ssh_tunnels?:TunnelRule[]};

export function TunnelPortConflictPrompt({hosts,notice,configureSudo}:{
  hosts:Host[];notice:(message:string)=>void;configureSudo:(hostId:string,ruleId:string)=>void;
}){
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
      const canConfigure=!process&&conflict.reason!=='ambiguous_owner';
      async function decide(accepted:boolean){
        if(handled.current.has(confirmation))return;
        handled.current.add(confirmation);
        setSubmitting(true);
        try{
          const decision=accepted&&process?'release':'dismiss';
          const path=`/${encodeURIComponent(rule.id)}/port-conflict/${decision}`;
          const result=await tunnelRequest(host.id,path,'POST',{confirmation});
          if(accepted&&canConfigure)configureSudo(host.id,rule.id);
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
      if(!process)return <AppConfirm key={confirmation}
        heading={t('远端端口被占用','Remote port is in use')}
        message={canConfigure?t(
          `${machine} 上的 ${listeners} 正在监听。当前 SSH 会话无法核实占用进程。验证该机器的 sudo 权限后，Workbench 会重新检查，再请你确认是否结束进程。`,
          `${listeners} is listening on ${machine}. This SSH session could not verify the owner. Verify sudo access for this machine so Workbench can check again and ask before stopping the process.`
        ):t(
          `${machine} 上的 ${listeners} 正在监听，但无法核实单个占用进程。请让服务器管理员检查这条监听。`,
          `${listeners} is listening on ${machine}, but Workbench could not verify a single owner. Ask the server administrator to check the listener.`
        )}
        confirmLabel={t('配置 sudo 并重新检查','Configure sudo and check again')}
        cancelLabel={t('关闭','Close')}
        hideConfirm={!canConfigure}
        finish={accepted=>void decide(accepted)}/>;
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
