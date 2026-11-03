import type {CommandLine} from './terminalSuggestions';
export const isArchivePath=(path:string)=>/\.(?:tar(?:\.gz|\.bz2|\.xz)?|tgz|tbz2|zip)$/i.test(path);
const safePath=(path:string)=>path.length>0&&path.length<=4096&&!/[\x00-\x1f\x7f\\]/.test(path)&&!path.split('/').includes('..');
const quote=(path:string)=>"'"+path.replace(/'/g,"'\\''")+"'";
export function archiveCommand(path:string,cwd?:string):string|undefined{
 if(!safePath(path)||!isArchivePath(path)||path.includes('://'))return;
 if(!path.startsWith('/')){
  if(!cwd?.startsWith('/')||!safePath(cwd)||! /^(?:\.\/)?[\p{L}\p{N}_-]/u.test(path))return;
  path=cwd.replace(/\/$/,'')+'/'+path.replace(/^\.\//,'');
 }
 const parent=path.slice(0,path.lastIndexOf('/'))||'/';
 return /\.zip$/i.test(path)?`unzip -n ${quote(path)} -d ${quote(parent)}`:`tar -xf ${quote(path)} -C ${quote(parent)} --keep-old-files`;
}
export function canFillArchive(atPrompt:boolean,line:CommandLine){return atPrompt&&line.valid&&line.text===''&&line.cursor===0}
