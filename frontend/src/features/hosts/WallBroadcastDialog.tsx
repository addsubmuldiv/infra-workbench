import {useId,useRef,useState} from 'react';
import {Megaphone} from 'lucide-react';
import {dateLocale,t,useLocale} from '../../shared/i18n';
import {ModalDialog} from '../../shared/ModalDialog';
import './wallBroadcast.css';

export type WallBroadcast={id:string;host_id:string;host:string;target?:string;created:number;message:string;truncated:boolean};

export function WallBroadcastDialog({broadcast,onAcknowledge}:{
  broadcast:WallBroadcast;
  onAcknowledge:()=>Promise<void>;
}){
  useLocale();
  const title=useId(),details=useId();
  const inFlight=useRef(false);
  const [busy,setBusy]=useState(false),[failed,setFailed]=useState(false);
  const dismiss=async()=>{
    if(inFlight.current)return;
    inFlight.current=true;
    setBusy(true);
    setFailed(false);
    try{await onAcknowledge()}
    catch{setFailed(true)}
    finally{inFlight.current=false;setBusy(false)}
  };
  const received=new Date(broadcast.created*1000);
  return <ModalDialog className="modal wall-broadcast-dialog" labelledBy={title} describedBy={details} onDismiss={()=>void dismiss()}>
    <div className="wall-broadcast-heading">
      <Megaphone size={24} aria-hidden="true"/>
      <h2 id={title} data-dialog-focus tabIndex={-1}>{t('机器广播','Machine broadcast')}</h2>
    </div>
    <dl className="wall-broadcast-details" id={details}>
      <div>
        <dt>{t('来源机器','Source machine')}</dt>
        <dd><strong><bdi>{broadcast.host}</bdi></strong>
          {broadcast.target&&broadcast.target!==broadcast.host&&<bdi className="wall-broadcast-target">{broadcast.target}</bdi>}
        </dd>
      </div>
      <div>
        <dt>{t('接收时间','Received at')}</dt>
        <dd><time dateTime={received.toISOString()}>{received.toLocaleString(dateLocale())}</time></dd>
      </div>
    </dl>
    <pre dir="auto" className="wall-broadcast-message" tabIndex={0}>{broadcast.message}</pre>
    {broadcast.truncated&&<p className="subtle">{t('消息过长，已截断。','The message was truncated.')}</p>}
    {failed&&<p role="alert" className="subtle">{t('暂时无法确认这条广播，请重试。','Could not acknowledge this broadcast. Try again.')}</p>}
    <div className="modal-footer"><button className="primary" disabled={busy} onClick={()=>void dismiss()}>{t('知道了','Got it')}</button></div>
  </ModalDialog>;
}
