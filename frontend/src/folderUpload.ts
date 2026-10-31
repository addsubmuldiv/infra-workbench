export type FolderHandle={kind:'directory';name:string;entries:()=>AsyncIterable<[string,FolderHandle|{kind:'file';name:string;getFile:()=>Promise<File>}]>};
export type FolderSelection={name:string;files:{path:string;file:File}[];directories:string[];preservesEmpty:boolean};
const MAX_BYTES=512*1024*1024,MAX_ENTRIES=10000;
const aborted=()=>new DOMException('文件夹上传已取消','AbortError');
function components(path:string):string[]{
  const parts=path.split('/');
  if(!path||path.length>4096||parts.length>64||/[\\\0\r\n:]/.test(path)||parts.some(part=>!part||part==='.'||part==='..'||new TextEncoder().encode(part).length>255))throw new Error('文件夹包含无效的相对路径或目录层级超过 64 层');
  return parts;
}
function validate(selection:FolderSelection){
  if(components(selection.name).length!==1)throw new Error('文件夹名称无效');
  const files=new Set<string>(),dirs=new Set<string>();let bytes=0;
  for(const path of selection.directories){components(path);if(dirs.has(path))throw new Error('文件夹包含重复目录');dirs.add(path)}
  for(const {path,file} of selection.files){components(path);if(files.has(path))throw new Error('文件夹包含重复文件');files.add(path);bytes+=file.size}
  if(bytes>MAX_BYTES)throw new Error('文件夹总大小不能超过 512 MiB');
  for(const path of [...files,...dirs]){
    const parts=components(path);for(let i=1;i<parts.length;i++)dirs.add(parts.slice(0,i).join('/'));
    if(files.size+dirs.size>MAX_ENTRIES)throw new Error('文件夹最多支持 10000 项');
  }
  if([...files].some(path=>dirs.has(path)))throw new Error('文件与目录路径冲突');
  return [...dirs].sort();
}
export function folderFromFiles(files:File[]):FolderSelection{
  if(!files.length)throw new Error('未读取到文件；上传空文件夹需要浏览器支持目录选择器');
  if(files.length>MAX_ENTRIES)throw new Error('文件夹最多支持 10000 项');
  const first=components(files[0].webkitRelativePath),name=first[0];
  const selection:FolderSelection={name,files:[],directories:[],preservesEmpty:false};
  for(const file of files){const parts=components(file.webkitRelativePath);if(parts.length<2||parts[0]!==name)throw new Error('请每次选择一个完整文件夹');selection.files.push({path:parts.slice(1).join('/'),file})}
  selection.directories=validate(selection);return selection;
}
export async function readFolder(root:FolderHandle,signal:AbortSignal,onScan?:(entries:number)=>void):Promise<FolderSelection>{
  const selection:FolderSelection={name:root.name,files:[],directories:[],preservesEmpty:true};let entries=0,bytes=0;
  async function visit(handle:FolderHandle,prefix:string,depth:number){
    if(signal.aborted)throw aborted();if(depth>64)throw new Error('目录层级超过 64 层');
    for await(const [name,entry] of handle.entries()){
      if(signal.aborted)throw aborted();if(++entries>MAX_ENTRIES)throw new Error('文件夹最多支持 10000 项');
      if(components(name).length!==1)throw new Error('文件夹包含无效名称');const path=prefix+name;components(path);
      if(entry.kind==='directory'){selection.directories.push(path);await visit(entry,path+'/',depth+1)}
      else{const file=await entry.getFile();if(signal.aborted)throw aborted();bytes+=file.size;if(bytes>MAX_BYTES)throw new Error('文件夹总大小不能超过 512 MiB');selection.files.push({path,file})}
      onScan?.(entries);
    }
  }
  await visit(root,'',0);selection.directories=validate(selection);return selection;
}
export function folderPayload(selection:FolderSelection):Blob{
  const directories=validate(selection),manifest=JSON.stringify({version:1,files:selection.files.map(({path,file})=>({path,size:file.size})),directories})+'\n';
  if(new TextEncoder().encode(manifest).length>1024*1024)throw new Error('文件夹清单过大，请选择更具体的子目录');
  // Blob references file data; preparing the bundle does not read all bytes into JS memory.
  const body=new Blob(['IWB_FOLDER:1\n',manifest,...selection.files.map(({file})=>file)]);
  if(body.size>MAX_BYTES)throw new Error('文件夹及清单总大小不能超过 512 MiB');
  return body;
}
