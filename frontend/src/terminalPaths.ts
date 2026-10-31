import type {Terminal,ILink,ILinkProvider,IBufferRange} from '@xterm/xterm';

// Recognize a complete output line, such as pwd. No shell commands or URLs run.
export function directoryPathLink(term:Pick<Terminal,'buffer'|'cols'>,lineNumber:number):{path:string;range:IBufferRange}|undefined{
  const buffer=term.buffer.active;
  if(buffer.type!=='normal')return;
  let first=lineNumber-1,last=first;
  while(first>0&&buffer.getLine(first)?.isWrapped){if(last-first>=32)return;first--}
  if(!buffer.getLine(first)?.translateToString(true).trimStart().startsWith('/'))return;
  while(buffer.getLine(last+1)?.isWrapped){if(last-first>=32)return;last++}
  let text='';
  const positions:{x:number;y:number;width:number}[]=[];
  for(let row=first;row<=last;row++){
    const line=buffer.getLine(row);if(!line)return;
    for(let column=0;column<Math.min(term.cols,line.length);column++){
      const cell=line.getCell(column);if(!cell||cell.getWidth()===0)continue;
      // A wide CJK glyph can wrap with an unused final cell on the prior row.
      if(!cell.getChars()&&row<last&&column===term.cols-1&&buffer.getLine(row+1)?.getCell(0)?.getWidth()===2)continue;
      const chars=cell.getChars()||' ';
      text+=chars;
      for(let index=0;index<chars.length;index++)positions.push({x:column+1,y:row+1,width:cell.getWidth()});
      if(text.length>4608)return;
    }
  }
  const path=text.trim();
  if(!path.startsWith('/')||path.length>4096||/[\x00-\x1f\x7f]/.test(path))return;
  const start=text.indexOf(path),end=start+path.length-1;
  return {path,range:{start:{x:positions[start].x,y:positions[start].y},end:{x:positions[end].x+positions[end].width-1,y:positions[end].y}}};
}

export function directoryLinkProvider(term:Pick<Terminal,'buffer'|'cols'>,open:(path:string)=>void):ILinkProvider{
  return {provideLinks(lineNumber,callback){
    const match=directoryPathLink(term,lineNumber);
    if(!match){callback(undefined);return}
    const link:ILink={text:match.path,range:match.range,decorations:{pointerCursor:false,underline:false},
      hover:event=>{if(link.decorations){link.decorations.pointerCursor=event.ctrlKey;link.decorations.underline=event.ctrlKey}},
      activate:event=>{if(!event.ctrlKey||event.button!==0)return;event.preventDefault();open(match.path)}};
    callback([link]);
  }};
}
