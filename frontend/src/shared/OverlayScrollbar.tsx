import React,{useEffect,useRef,type RefObject} from 'react';
import './overlayScrollbar.css';

const IDLE_MS=650;
const MIN_THUMB_HEIGHT=28;

export function OverlayScrollbar({className,scrollRef}:{
  className?:string;
  scrollRef?:RefObject<HTMLElement|null>;
}){
  const track=useRef<HTMLDivElement>(null);
  const thumb=useRef<HTMLDivElement>(null);

  useEffect(()=>{
    const trackElement=track.current;
    const thumbElement=thumb.current;
    const scroller=scrollRef?scrollRef.current:document.scrollingElement;
    if(!trackElement||!thumbElement||!scroller)return;

    const scrollTarget=scrollRef?scroller:window;
    let idleTimer:number|undefined;
    let drag:{pointerId:number;y:number;scrollTop:number;scale:number}|undefined;

    const hide=()=>{trackElement.removeAttribute('data-scrolling')};
    const hideAfterIdle=()=>{
      window.clearTimeout(idleTimer);
      if(!drag)idleTimer=window.setTimeout(hide,IDLE_MS);
    };
    const measure=()=>{
      const height=trackElement.clientHeight;
      const {clientHeight,scrollHeight,scrollTop}=scroller;
      const scrollRange=scrollHeight-clientHeight;
      if(height<=0||scrollRange<=0)return;
      const thumbHeight=Math.min(height,Math.max(MIN_THUMB_HEIGHT,height*clientHeight/scrollHeight));
      const travel=height-thumbHeight;
      const progress=Math.max(0,Math.min(1,scrollTop/scrollRange));
      thumbElement.style.height=`${thumbHeight}px`;
      thumbElement.style.transform=`translateY(${travel*progress}px)`;
      return {travel,scrollRange};
    };
    const onScroll=()=>{
      if(!measure()){hide();return}
      trackElement.setAttribute('data-scrolling','');
      hideAfterIdle();
    };
    const startDrag=(event:PointerEvent)=>{
      if(event.button!==0||drag)return;
      const size=measure();
      if(!size?.travel)return;
      event.preventDefault();
      thumbElement.setPointerCapture(event.pointerId);
      drag={pointerId:event.pointerId,y:event.clientY,scrollTop:scroller.scrollTop,scale:size.scrollRange/size.travel};
      hideAfterIdle();
    };
    const moveDrag=(event:PointerEvent)=>{
      if(drag?.pointerId!==event.pointerId)return;
      scroller.scrollTop=drag.scrollTop+(event.clientY-drag.y)*drag.scale;
    };
    const endDrag=(event:PointerEvent)=>{
      if(drag?.pointerId!==event.pointerId)return;
      drag=undefined;
      hideAfterIdle();
    };
    const resize=new ResizeObserver(()=>{
      if(trackElement.hasAttribute('data-scrolling')&&!measure())hide();
    });
    resize.observe(trackElement);
    scrollTarget.addEventListener('scroll',onScroll,{passive:true});
    thumbElement.addEventListener('pointerdown',startDrag);
    thumbElement.addEventListener('pointermove',moveDrag);
    thumbElement.addEventListener('lostpointercapture',endDrag);
    return ()=>{
      resize.disconnect();
      window.clearTimeout(idleTimer);
      hide();
      scrollTarget.removeEventListener('scroll',onScroll);
      thumbElement.removeEventListener('pointerdown',startDrag);
      thumbElement.removeEventListener('pointermove',moveDrag);
      thumbElement.removeEventListener('lostpointercapture',endDrag);
    };
  },[scrollRef]);

  return <div ref={track} className={className?`overlay-scrollbar ${className}`:'overlay-scrollbar'} aria-hidden="true">
    <div ref={thumb} className="overlay-scrollbar-thumb"/>
  </div>;
}
