import React,{useEffect,useState} from 'react';
import {scheduleDrawerEntrance} from './drawerMotion';

export function DeviceDrawerFrame({children,onClose}:{children:React.ReactNode;onClose:()=>void}){
  const [entered,setEntered]=useState(false);
  useEffect(()=>scheduleDrawerEntrance(
    ()=>setEntered(true),
    callback=>window.requestAnimationFrame(callback),
    id=>window.cancelAnimationFrame(id),
  ),[]);
  return <div className="drawer-shade" data-entered={entered} onClick={onClose}>{children}</div>;
}
