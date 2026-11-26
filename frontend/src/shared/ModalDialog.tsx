import {useLayoutEffect,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import './modalDialog.css';

type Props={
  className:string;
  labelledBy:string;
  describedBy?:string;
  onDismiss:()=>void;
  children:ReactNode;
};

function tabbableElements(element:HTMLElement){
  return Array.from(element.querySelectorAll<HTMLElement>('button,input,select,textarea,a[href],[tabindex]'))
    .filter(node=>node.tabIndex>=0&&!node.matches(':disabled')&&node.getClientRects().length>0);
}

export function ModalDialog({className,labelledBy,describedBy,onDismiss,children}:Props){
  const native=typeof HTMLDialogElement!=='undefined'&&typeof HTMLDialogElement.prototype.showModal==='function';
  const dialog=useRef<HTMLDialogElement>(null),fallback=useRef<HTMLElement>(null);
  const dismiss=useRef(onDismiss);
  dismiss.current=onDismiss;

  useLayoutEffect(()=>{
    if(native){
      const element=dialog.current!;
      element.querySelector('[data-dialog-focus]')?.setAttribute('autofocus','');
      element.showModal();
      return()=>element.close();
    }

    // Safari before 15.4 uses the existing overlay and keeps focus inside it.
    const element=fallback.current!;
    const previous=document.activeElement;
    const focusStart=()=>{
      const controls=tabbableElements(element);
      (controls.find(node=>node.hasAttribute('data-dialog-focus'))??controls[0]??element).focus();
    };
    const containFocus=(event:FocusEvent)=>{
      if(event.target instanceof Node&&!element.contains(event.target))focusStart();
    };
    const onKeyDown=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();dismiss.current();return;
      }
      if(event.key!=='Tab')return;
      const controls=tabbableElements(element);
      const active=document.activeElement;
      if(!controls.includes(active as HTMLElement)||active===(event.shiftKey?controls[0]:controls[controls.length-1])){
        event.preventDefault();
        (controls[event.shiftKey?controls.length-1:0]??element).focus();
      }
    };
    focusStart();
    document.addEventListener('focusin',containFocus);
    element.addEventListener('keydown',onKeyDown);
    return()=>{
      document.removeEventListener('focusin',containFocus);
      element.removeEventListener('keydown',onKeyDown);
      if(previous instanceof HTMLElement&&previous.isConnected)previous.focus();
    };
  },[native]);

  const name={'aria-labelledby':labelledBy,'aria-describedby':describedBy};
  return createPortal(native?<dialog ref={dialog} {...name} className={'workbench-modal '+className}
    onCancel={event=>{event.preventDefault();onDismiss()}}>{children}</dialog>:
    <div className="modal-shade"><section ref={fallback} {...name} className={'workbench-modal '+className}
      role="dialog" aria-modal="true" tabIndex={-1}>{children}</section></div>,document.body);
}
