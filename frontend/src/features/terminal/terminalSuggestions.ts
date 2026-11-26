export type CommandLine={text:string;cursor:number;valid:boolean};
export type HistoryCommand={command:string;cwd?:string;created?:number};
export const emptyCommandLine=():CommandLine=>({text:'',cursor:0,valid:true});
const previous=(text:string,index:number)=>Math.max(0,index-(index>1&&/[\uDC00-\uDFFF]/.test(text[index-1])?2:1));
const following=(text:string,index:number)=>Math.min(text.length,index+(text.codePointAt(index)!>0xffff?2:1));
export function editCommandLine(line:CommandLine,input:string):CommandLine{
  if(!line.valid)return line;
  let {text,cursor}=line;
  if(input==='\x15')return {text:text.slice(cursor),cursor:0,valid:true};
  if(input==='\x01'||input==='\x1b[H'||input==='\x1bOH')return {...line,cursor:0};
  if(input==='\x05'||input==='\x1b[F'||input==='\x1bOF')return {...line,cursor:text.length};
  if(input==='\x1b[D'||input==='\x1bOD')return {...line,cursor:previous(text,cursor)};
  if(input==='\x1b[C'||input==='\x1bOC')return {...line,cursor:following(text,cursor)};
  if(input==='\x7f'||input==='\b'){const start=previous(text,cursor);return {text:text.slice(0,start)+text.slice(cursor),cursor:start,valid:true}}
  if(input==='\x1b[3~')return {...line,text:text.slice(0,cursor)+text.slice(following(text,cursor))};
  if(input==='\x0c')return line;
  if(/[\x00-\x1f\x7f]/.test(input)||text.length+input.length>2048)return {...line,valid:false};
  text=text.slice(0,cursor)+input+text.slice(cursor);cursor+=input.length;return {text,cursor,valid:true};
}
export function historySuggestion(line:CommandLine,history:HistoryCommand[]):string{
  if(!line.valid||!line.text||line.cursor!==line.text.length)return '';
  const match=history.find(item=>item.command.length>line.text.length&&item.command.startsWith(line.text));
  return match?.command.slice(line.text.length)??'';
}
