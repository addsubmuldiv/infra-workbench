// Leave a painted, off-screen frame before starting compositor transitions.
export function scheduleDrawerEntrance(
  start:()=>void,
  request:(callback:()=>void)=>number,
  cancel:(id:number)=>void,
){
  let frame=request(()=>{frame=request(start)});
  return ()=>cancel(frame);
}
