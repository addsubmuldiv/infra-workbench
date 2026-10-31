/** Bounded ordering for non-modal windows. Moving focus never consumes the event. */
const orders=new WeakMap<Document,HTMLElement[]>();
export function registerFloatingWindow(element:HTMLElement|null){
  if(!element)return;
  const doc=element.ownerDocument;
  const present=Array.from(doc.querySelectorAll<HTMLElement>('[data-floating-window]'));
  const order=(orders.get(doc)||[]).filter(item=>present.includes(item)&&item!==element);
  for(const item of present)if(item!==element&&!order.includes(item))order.push(item);
  order.push(element);
  order.forEach((item,index)=>{item.style.zIndex=String(70+index)});
  orders.set(doc,order);
}
export function activateFloatingWindow(event:{currentTarget:HTMLElement;target:EventTarget|null}){
  // React portals bubble through their logical parents. Raise the actual window,
  // not the terminal/file browser which happens to own the portal component.
  const owner=(event.target as HTMLElement|null)?.closest?.('[data-floating-window]');
  if(owner&&owner!==event.currentTarget)return;
  registerFloatingWindow(event.currentTarget);
}
