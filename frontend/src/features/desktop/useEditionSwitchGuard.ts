import {useEffect} from 'react';
import {canRestartForUpdate} from './desktopUpdates';

const beforeSwitch='iwb:before-edition-switch';

export function canSwitchEdition(target:Window,hasUnsaved:()=>boolean){
  return canRestartForUpdate(target,hasUnsaved)&&target.dispatchEvent(new Event(beforeSwitch,{cancelable:true}));
}

export function useEditionSwitchGuard(dirty:boolean){
  useEffect(()=>{
    if(!dirty)return;
    const block=(event:Event)=>event.preventDefault();
    window.addEventListener(beforeSwitch,block);
    return()=>window.removeEventListener(beforeSwitch,block);
  },[dirty]);
}
