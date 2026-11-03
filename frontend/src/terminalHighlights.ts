import type {Terminal,IBufferLine} from '@xterm/xterm';
export type HighlightRule={text:string;color:string;enabled:boolean};
export type HighlightPreferences={enabled:boolean;rules:HighlightRule[]};
export const HIGHLIGHTS_KEY='infra-workbench:terminal-highlights:v1';
export const DEFAULT_HIGHLIGHTS:HighlightPreferences={enabled:true,rules:[
 {text:'Traceback',color:'#991b1b',enabled:true},{text:'CUDA out of memory',color:'#991b1b',enabled:true},
 {text:'NaN',color:'#92400e',enabled:true},{text:'NCCL',color:'#1e40af',enabled:true},
 {text:'checkpoint',color:'#166534',enabled:true},{text:'success',color:'#166534',enabled:true}]};
export function normalizeHighlights(raw:unknown):HighlightPreferences{
 const value=raw as Partial<HighlightPreferences>|null;
 return {enabled:typeof value?.enabled==='boolean'?value.enabled:true,rules:(Array.isArray(value?.rules)?value.rules:DEFAULT_HIGHLIGHTS.rules).slice(0,20).filter((r):r is HighlightRule=>!!r&&typeof r.text==='string'&&r.text.trim().length>0&&r.text.length<=128&&!/[\x00-\x1f\x7f]/.test(r.text)&&typeof r.color==='string'&&/^#[0-9a-f]{6}$/i.test(r.color)).map(r=>({text:r.text,color:r.color,enabled:r.enabled!==false}))};
}
export function readHighlights(storage:Pick<Storage,'getItem'>):HighlightPreferences{try{return normalizeHighlights(JSON.parse(storage.getItem(HIGHLIGHTS_KEY)||'null'))}catch{return normalizeHighlights(null)}}
export function matchHighlightLine(line:Pick<IBufferLine,'length'|'getCell'>,rules:HighlightRule[]){
 let text='';const columns:number[]=[],ends:number[]=[];
 for(let x=0;x<Math.min(line.length,500);x++){
  const cell=line.getCell(x);if(!cell||cell.getWidth()===0)continue;
  const chars=cell.getChars()||' ';for(let i=0;i<chars.length;i++){columns.push(x);ends.push(x+cell.getWidth())}text+=chars;
 }
 const matches:{x:number;width:number;color:string}[]=[];
 for(const rule of rules.slice(0,20)){if(!rule.enabled||!rule.text)continue;let from=0;
  while(matches.length<400){const index=text.indexOf(rule.text,from);if(index<0)break;const end=index+rule.text.length-1;matches.push({x:columns[index],width:ends[end]-columns[index],color:rule.color});from=end+1}
 }
 return matches;
}
export function createTerminalHighlights(term:Terminal,preferences:()=>HighlightPreferences){
 let resources:{dispose:()=>void}[]=[],count=0,writeGeneration=0,signature='',disposed=false,timer:ReturnType<typeof setTimeout>|undefined;
 const clear=()=>{for(const resource of resources.reverse())resource.dispose();resources=[];count=0};
 const refresh=()=>{
  if(disposed)return;const prefs=preferences(),buffer=term.buffer.active;
  if(!prefs.enabled||buffer.type==='alternate'){signature='';clear();return}
  const rows:{y:number;matches:ReturnType<typeof matchHighlightLine>}[]=[];let remaining=400;
  for(let y=buffer.viewportY;y<buffer.viewportY+Math.min(term.rows,200)&&remaining>0;y++){
   const line=buffer.getLine(y);if(!line)continue;const matches=matchHighlightLine(line,prefs.rules).slice(0,remaining);remaining-=matches.length;if(matches.length)rows.push({y,matches});
  }
  const next=JSON.stringify([writeGeneration,buffer.baseY,buffer.cursorY,rows]);if(next===signature)return;signature=next;clear();
  for(const row of rows){const marker=term.registerMarker(row.y-buffer.baseY-buffer.cursorY);if(!marker)continue;resources.push(marker);
   for(const match of row.matches){const decoration=term.registerDecoration({marker,x:match.x,width:match.width,backgroundColor:match.color,foregroundColor:'#ffffff',layer:'bottom'});if(decoration){resources.push(decoration);count++}}
  }
 };
 const schedule=()=>{if(!disposed&&timer===undefined)timer=setTimeout(()=>{timer=undefined;refresh()},100)};
 const subscriptions=[term.onRender(schedule),term.onScroll(schedule),term.onWriteParsed(()=>{writeGeneration++;schedule()})];schedule();
 return {refresh,count:()=>count,dispose(){disposed=true;if(timer!==undefined)clearTimeout(timer);subscriptions.forEach(s=>s.dispose());clear()}};
}
