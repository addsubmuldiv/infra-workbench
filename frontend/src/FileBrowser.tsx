import React,{useEffect,useRef,useState} from 'react';
import {ArrowUp,Upload,Search,Terminal,ClipboardPaste,Copy,Scissors,FilePlus,FolderPlus,MoreHorizontal,ChevronDown,ChevronRight,Download,File,Folder,FolderOpen,Home,LoaderCircle,RefreshCw,Minus,PanelTopOpen,X} from 'lucide-react';
import {listDirectory,fileOperation,searchFiles,type DirectoryPage,type RemoteEntry} from './files';
import {downloadOriginalLog} from './logDownload';
import './files.css';
import {uploadFile,watchDownload,type TransferProgress} from './fileTransfers';
import {FileEditor} from './FileEditor';
import {FileActionDialog,type FileAction} from './FileActionDialog';
import {fitFileWindow,moveFileWindow,type WindowFrame} from './fileWindow';

type Host={id:string;target:string};
const parentDirectory=(path:string)=>path.slice(0,path.lastIndexOf('/'))||'/';
const size=(n:number|null)=>n==null?'—':n<1024?n+' B':n<1024**2?(n/1024).toFixed(1)+' KiB':n<1024**3?(n/1024**2).toFixed(1)+' MiB':(n/1024**3).toFixed(1)+' GiB';
export function FileBrowser({host,hosts,close,requestId=host.id,initialPath,onTerminal}:{host:Host;hosts:Host[];close:()=>void;requestId?:string;initialPath?:string;onTerminal?:(hostId:string,path:string)=>void}){
  const [selected,setSelected]=useState(host.id);
  const [navigation,setNavigation]=useState({host:host.id,id:requestId,path:initialPath??'~'});
  const [locked,setLocked]=useState(false);
  const [minimized,setMinimized]=useState(false);
  const viewport=()=>({width:window.innerWidth,height:window.innerHeight});
  const [frame,setFrame]=useState(()=>fitFileWindow({x:(window.innerWidth-880)/2,y:40,width:880,height:Math.min(600,window.innerHeight-120)},viewport()));
  const gesture=useRef<{pointer:number;kind:'move'|'resize';x:number;y:number;frame:WindowFrame}|null>(null);
  useEffect(()=>{const resize=()=>setFrame(old=>fitFileWindow(old,viewport()));window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize)},[]);
  const startGesture=(event:React.PointerEvent,kind:'move'|'resize')=>{
    if(event.button!==0||gesture.current)return;
    if(kind==='move'&&(event.target as HTMLElement).closest('button,select,input,a'))return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current={pointer:event.pointerId,kind,x:event.clientX,y:event.clientY,frame};
  };
  const moveGesture=(event:React.PointerEvent)=>{
    const start=gesture.current;if(!start||start.pointer!==event.pointerId)return;
    const dx=event.clientX-start.x,dy=event.clientY-start.y;
    setFrame(start.kind==='move'?moveFileWindow(start.frame,dx,dy,viewport(),minimized):fitFileWindow({...start.frame,width:start.frame.width+dx,height:start.frame.height+dy},viewport()));
  };
  const endGesture=(event:React.PointerEvent)=>{if(gesture.current?.pointer===event.pointerId)gesture.current=null};
  const toggleMinimized=()=>{if(minimized)setFrame(old=>fitFileWindow(old,viewport()));setMinimized(!minimized)};
  const editorClose=useRef<((after?:()=>void)=>void)|null>(null);
  const leave=(after:()=>void)=>{if(locked)return;if(editorClose.current)editorClose.current(after);else after()};
  const handledRequest=useRef(requestId);
  useEffect(()=>{
    if(handledRequest.current===requestId||locked)return;
    handledRequest.current=requestId;
    if(host.id!==selected||initialPath)leave(()=>{setSelected(host.id);setNavigation({host:host.id,id:requestId,path:initialPath??'~'});setMinimized(false)});
    else setMinimized(false);
  },[requestId,locked]);
  const current=hosts.find(item=>item.id===selected)||host;
  return <div className="file-workspace"><section role="dialog" aria-modal="false" aria-labelledby="file-title" className={'file-browser floating '+(minimized?'minimized':'')} style={{left:frame.x,top:frame.y,width:minimized?'min(320px, calc(100vw - 16px))':frame.width,height:minimized?56:frame.height}} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} onLostPointerCapture={endGesture}>
    <header className="file-header" onPointerDown={event=>startGesture(event,'move')}><div tabIndex={0} aria-label="移动文件窗口，方向键调整位置" onKeyDown={event=>{if(event.target!==event.currentTarget)return;const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>moveFileWindow(old,...offset,viewport(),minimized))}}}><h2 id="file-title"><FolderOpen size={19}/>服务器文件{minimized&&<small>{current.target}</small>}</h2>{!minimized&&<p>拖动标题栏移动窗口；右下角调整大小，可同时操作 SSH 终端。</p>}</div>{!minimized&&<select aria-label="文件浏览目标机器" value={current.id} disabled={locked} onChange={e=>leave(()=>setSelected(e.target.value))}>{hosts.map(item=><option key={item.id} value={item.id}>{item.target}</option>)}</select>}<button className="icon-button" aria-label={minimized?'恢复文件窗口':'最小化文件窗口'} title={minimized?'恢复文件窗口':'最小化（保留目录和编辑状态）'} onClick={toggleMinimized}>{minimized?<PanelTopOpen size={18}/>:<Minus size={18}/>}</button><button className="icon-button" aria-label="关闭文件浏览" disabled={locked} onClick={()=>leave(close)}><X size={20}/></button></header>
    <div className="file-window-body" hidden={minimized}><BrowserBody key={current.id} host={current} onTerminal={path=>onTerminal?.(current.id,path)} navigation={navigation.host===current.id?navigation:undefined} onBusy={setLocked} editorClose={editorClose}/></div>
    {!minimized&&<div className="file-window-resize" role="separator" aria-label="调整文件窗口大小" tabIndex={0} onPointerDown={event=>startGesture(event,'resize')} onKeyDown={event=>{const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>fitFileWindow({...old,width:old.width+offset[0],height:old.height+offset[1]},viewport()))}}}/>}
  </section></div>;
}
function BrowserBody({host,onBusy,editorClose,navigation,onTerminal}:{host:Host;onTerminal?:(path:string)=>void;onBusy:(busy:boolean)=>void;editorClose:React.RefObject<((after?:()=>void)=>void)|null>;navigation?:{id:string;path:string}}){
  const [root,setRoot]=useState<DirectoryPage|null>(null),[path,setPath]=useState('~');
  const [pages,setPages]=useState<Record<string,DirectoryPage>>({}),[opened,setOpened]=useState<Set<string>>(new Set());
  const [loading,setLoading]=useState<Set<string>>(new Set()),[errors,setErrors]=useState<Record<string,string>>({});
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[downloading,setDownloading]=useState('');
  const [selected,setSelected]=useState<RemoteEntry|null>(null),[clipboard,setClipboard]=useState<{entry:RemoteEntry;op:'copy'|'move'}|null>(null);
  const currentDirectory=selected?(selected.kind==='directory'?selected.path:parentDirectory(selected.path)):root?.path;
  const [action,setAction]=useState<FileAction|null>(null),[operationBusy,setOperationBusy]=useState(false),[editorBusy,setEditorBusy]=useState(false),[editor,setEditor]=useState<string|null>(null);
  const [supported,setSupported]=useState(false);
  const [features,setFeatures]=useState({upload:false,search:false,cwd:false,progress:false});
  const [transfer,setTransfer]=useState<(TransferProgress&{id:string;name:string;direction:'upload'|'download'})|null>(null);
  const [query,setQuery]=useState(''),[recursive,setRecursive]=useState(false),[realtime,setRealtime]=useState(false),[searchResult,setSearchResult]=useState<DirectoryPage|null>(null);
  const uploadRequest=useRef<AbortController|null>(null),uploadInput=useRef<HTMLInputElement>(null),directoryRef=useRef(currentDirectory);directoryRef.current=currentDirectory;
  useEffect(()=>{let active=true;fetch('/api/files/capabilities').then(response=>response.ok?response.json():null).then(data=>{if(active){setSupported(data?.editing===true);setFeatures({upload:!!data?.upload,search:!!data?.search,cwd:!!data?.terminal_cwd,progress:!!data?.transfer_progress})}}).catch(()=>{});return()=>{active=false}},[]);
  useEffect(()=>{onBusy(operationBusy||editorBusy);return()=>onBusy(false)},[operationBusy,editorBusy]);
  const [menu,setMenu]=useState<{entry:RemoteEntry;x:number;y:number}|null>(null);
  const mounted=useRef(true),epoch=useRef(0),menuRef=useRef<HTMLDivElement>(null),downloadRequest=useRef<AbortController|null>(null);
  const openRoot=async(value:string)=>{
    const request=++epoch.current;setLoading(new Set(['root']));setError('');setMenu(null);setSearchResult(null);setQuery('');
    try{const data=await listDirectory(host.id,value);if(mounted.current&&request===epoch.current){setRoot(data);setSelected(null);setPath(data.path);setPages({[data.path]:data});setOpened(new Set([data.path]));setErrors({})}}
    catch(e){if(mounted.current&&request===epoch.current)setError(e instanceof Error?e.message:String(e))}
    finally{if(mounted.current&&request===epoch.current)setLoading(new Set())}
  };
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;epoch.current++;downloadRequest.current?.abort();uploadRequest.current?.abort()}},[]);
  useEffect(()=>{setEditor(null);void openRoot(navigation?.path??'~')},[navigation?.id]);
  useEffect(()=>{
    if(!menu)return;
    const outside=(e:PointerEvent)=>{if(!menuRef.current?.contains(e.target as Node))setMenu(null)};
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setMenu(null)};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key)};
  },[menu]);
  const load=async(directory:string,offset=0)=>{
    if(loading.has(directory))return;const request=epoch.current;
    setLoading(old=>new Set(old).add(directory));setErrors(old=>({...old,[directory]:''}));
    try{const data=await listDirectory(host.id,directory,offset);if(!mounted.current||request!==epoch.current)return;
      setPages(old=>({...old,[directory]:{...data,entries:offset?[...new Map([...(old[directory]?.entries||[]),...data.entries].map(item=>[item.path,item])).values()]:data.entries}}));
    }catch(e){if(mounted.current&&request===epoch.current)setErrors(old=>({...old,[directory]:e instanceof Error?e.message:String(e)}))}
    finally{if(mounted.current&&request===epoch.current)setLoading(old=>{const next=new Set(old);next.delete(directory);return next})}
  };
  const toggle=(entry:RemoteEntry)=>{if(!entry.accessible)return;setMenu(null);setOpened(old=>{const next=new Set(old);if(next.has(entry.path))next.delete(entry.path);else next.add(entry.path);return next});if(!pages[entry.path])void load(entry.path)};
  const selectEntry=(entry:RemoteEntry)=>{setSelected(entry);setPath(entry.kind==='directory'?entry.path:parentDirectory(entry.path))};
  const download=async(entry:RemoteEntry)=>{
    if(downloadRequest.current||uploadRequest.current)return;
    const controller=new AbortController(),watcher=new AbortController(),id=crypto.randomUUID();downloadRequest.current=controller;
    setMenu(null);setDownloading(entry.path);setError('');setMessage('');setTransfer({id,direction:'download',name:entry.name,stage:'download_remote',loaded:0,total:entry.size});
    const cancelRemote=()=>{if(features.progress)void fetch('/api/files/downloads/'+id,{method:'DELETE',headers:{'X-IWB':'1'}}).catch(()=>{})};
    controller.signal.addEventListener('abort',cancelRemote,{once:true});
    if(features.progress)void watchDownload(id,watcher.signal,value=>{if(mounted.current&&!controller.signal.aborted)setTransfer(old=>old?.id===id&&old.stage!=='download_browser'?{id,direction:'download',name:entry.name,...value}:old)}).catch(()=>{});
    try{const data=await downloadOriginalLog({host_id:host.id,path:entry.path,...(features.progress?{transfer_id:id}:{})},fetch,'/api/files/download',controller.signal,
        (loaded,total)=>{if(mounted.current&&!controller.signal.aborted)setTransfer({id,direction:'download',name:entry.name,stage:'download_browser',loaded,total})});
      if(!mounted.current)return;
      const url=URL.createObjectURL(data.blob),link=document.createElement('a');link.href=url;link.download=data.filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
      setMessage('已交给浏览器下载：'+entry.name);setTransfer({id,direction:'download',name:entry.name,stage:'done',loaded:data.blob.size,total:data.blob.size});
    }catch(e){if(mounted.current){setTransfer(null);if(controller.signal.aborted)setMessage('下载已取消');else setError((e instanceof Error?e.message:String(e)).replaceAll('日志','文件'))}}
    finally{watcher.abort();controller.signal.removeEventListener('abort',cancelRemote);if(downloadRequest.current===controller)downloadRequest.current=null;if(mounted.current)setDownloading('')}
  };
  const upload=async(files:File[])=>{
    if(!currentDirectory||!files.length||downloadRequest.current||uploadRequest.current)return;
    const directory=currentDirectory,controller=new AbortController();uploadRequest.current=controller;setError('');setMessage('');
    try{
      for(let index=0;index<files.length;index++){
        if(controller.signal.aborted)throw new DOMException('上传已取消','AbortError');
        const file=files[index],id=crypto.randomUUID(),name=(files.length>1?'['+(index+1)+'/'+files.length+'] ':'')+file.name;
        await uploadFile(host.id,directory,file,controller.signal,value=>{if(mounted.current&&!controller.signal.aborted)setTransfer({id,direction:'upload',name,...value})});
      }
      if(mounted.current){setMessage('已上传 '+files.length+' 个文件到 '+directory);if(directoryRef.current===directory)await openRoot(directory)}
    }catch(e){if(mounted.current){setTransfer(null);if(controller.signal.aborted)setMessage('已请求取消上传，请刷新目标目录确认结果');else setError(e instanceof Error?e.message:String(e))}}
    finally{if(uploadRequest.current===controller)uploadRequest.current=null}
  };
  const cancelTransfer=()=>{downloadRequest.current?.abort();uploadRequest.current?.abort()};
  const search=async()=>{
    if(!currentDirectory)return;if(!query.trim()){await openRoot(currentDirectory);return}
    const request=++epoch.current;setLoading(new Set(['root']));setError('');setMenu(null);
    try{const data=await searchFiles(host.id,currentDirectory,query,recursive,realtime);if(mounted.current&&request===epoch.current){setRoot(data);setSelected(null);setPath(data.path);setSearchResult(data);setPages({[data.path]:data});setOpened(new Set([data.path]));setErrors({})}}
    catch(e){if(mounted.current&&request===epoch.current)setError(e instanceof Error?e.message:String(e))}
    finally{if(mounted.current&&request===epoch.current)setLoading(new Set())}
  };
  const stage=(entry:RemoteEntry,op:'copy'|'move')=>{setClipboard({entry,op});setMenu(null);setMessage((op==='copy'?'已复制：':'已剪切：')+entry.name+'，请到目标目录点击粘贴。')};
  const paste=(directory:string)=>{if(clipboard){setMenu(null);setAction({op:clipboard.op,directory,source:clipboard.entry})}};
  const copyPath=async(entry:RemoteEntry)=>{setMenu(null);try{await navigator.clipboard.writeText(entry.path);setMessage('已复制路径')}catch{setError('无法写入系统剪贴板，请手动复制路径：'+entry.path)}};
  const switchEditor=(path:string)=>{if(editor===path)return;const open=()=>setEditor(path);if(editorClose.current)editorClose.current(open);else open()};
  const edit=(entry:RemoteEntry)=>{if(!supported){setError('文本编辑需要重启本地服务后启用');return}setMenu(null);switchEditor(entry.path)};
  const perform=async(destination:string)=>{
    if(!action)return;setOperationBusy(true);setError('');
    try{const command=action.op==='create'||action.op==='mkdir'?{op:action.op,path:destination}:{op:action.op==='rename'?'move' as const:action.op,path:action.source!.path,destination};
      await fileOperation(host.id,command);setMessage('操作完成：'+destination);if(action.op==='move')setClipboard(null);setSelected(null);
      const refreshDirectory=action.source?.kind==='directory'&&(action.op==='move'||action.op==='rename')&&currentDirectory===action.source.path?parentDirectory(action.source.path):currentDirectory;
      if(refreshDirectory)await openRoot(refreshDirectory);if(action.op==='create')switchEditor(destination);
    }finally{setOperationBusy(false)}
  };
  const context=(event:React.MouseEvent,entry:RemoteEntry)=>{if(!entry.accessible||entry.kind==='other')return;event.preventDefault();selectEntry(entry);setMenu({entry,x:Math.max(8,Math.min(event.clientX,window.innerWidth-210)),y:Math.max(8,Math.min(event.clientY,window.innerHeight-320))})};
  const children=(directory:string,depth:number):React.ReactNode=>{
    if(depth>40)return <p className="file-error">目录层级较深，请在路径栏直接打开该目录。</p>;
    const page=pages[directory];return <>
      {page?.entries.map(entry=><React.Fragment key={entry.path}><div className={'file-row '+(selected?.path===entry.path?'selected':'')} style={{paddingLeft:12+depth*20}} onContextMenu={e=>context(e,entry)}>
        <button className="file-name" disabled={!entry.accessible} title={entry.kind==='file'?'单击选中，双击或按 Enter 打开编辑器':undefined} aria-expanded={entry.kind==='directory'?opened.has(entry.path):undefined} aria-label={(entry.kind==='directory'?'展开目录 ':'文件 ')+entry.path} onClick={()=>{selectEntry(entry);if(entry.kind==='directory')toggle(entry)}} onDoubleClick={()=>{if(entry.kind==='file')edit(entry)}} onKeyDown={event=>{if(event.key==='Enter'&&entry.kind==='file'){event.preventDefault();selectEntry(entry);edit(entry)}}}>
          {entry.kind==='directory'?<>{opened.has(entry.path)?<ChevronDown size={14}/>:<ChevronRight size={14}/>}<Folder size={16}/></>:<><span className="file-indent"/><File size={15}/></>}<span title={entry.path}>{entry.relative??entry.name}{entry.symlink&&<small> ↗</small>}</span></button>
        <span className="file-size">{entry.kind==='directory'?'目录':size(entry.size)}</span><span className="file-date">{entry.modified?new Date(entry.modified*1000).toLocaleString('zh-CN',{hour12:false}):'—'}</span>
        {entry.kind==='file'&&<button className="icon-button" disabled={!!downloading||!entry.accessible} aria-label={'下载 '+entry.path} title="下载文件" onClick={()=>download(entry)}><Download size={14}/></button>}
        {entry.kind!=='other'&&<button className="icon-button" aria-label={'文件操作 '+entry.path} onClick={event=>context(event,entry)}><MoreHorizontal size={15}/></button>}
      </div>{entry.kind==='directory' &&opened.has(entry.path)&&children(entry.path,depth+1)}</React.Fragment>)}
      {loading.has(directory)&&<p className="file-inline" style={{paddingLeft:24+depth*20}}><LoaderCircle size={14} className="spin"/>正在读取目录…</p>}
      {errors[directory]&&<p className="file-error" style={{paddingLeft:24+depth*20}}>{errors[directory]} <button className="text-button" onClick={()=>load(directory)}>重试</button></p>}
      {page&&!page.entries.length&&!loading.has(directory)&&<p className="file-inline" style={{paddingLeft:24+depth*20}}>{searchResult?'没有匹配的文件':'空目录'}</p>}
      {page?.next_offset!=null&&<button className="text-button file-more" disabled={loading.has(directory)} style={{marginLeft:24+depth*20}} onClick={()=>load(directory,page.next_offset!)}>加载更多（已显示 {page.entries.length} / {page.total}）</button>}
    </>;
  };
  return <><form className="file-path" onSubmit={e=>{e.preventDefault();void openRoot(path)}}><button type="button" className="icon-button" aria-label="打开主目录" onClick={()=>openRoot('~')}><Home size={16}/></button><button type="button" className="icon-button" aria-label="打开上级目录" disabled={!currentDirectory||currentDirectory==='/'} onClick={()=>{if(currentDirectory)openRoot(parentDirectory(currentDirectory))}}><ArrowUp size={16}/></button><input aria-label="服务器目录路径" value={path} onChange={e=>setPath(e.target.value)} placeholder="~ 或 /data/训练目录"/><button className="secondary" disabled={loading.has('root')}>前往</button><button type="button" className="icon-button" aria-label="刷新文件目录" disabled={!currentDirectory||loading.has('root')} onClick={()=>{if(currentDirectory)openRoot(currentDirectory)}}><RefreshCw size={16}/></button></form>
    <form className="file-search" onSubmit={event=>{event.preventDefault();void search()}}><Search size={15}/><input aria-label="文件名搜索" placeholder="输入文件名关键词" value={query} onChange={event=>setQuery(event.target.value)}/><label><input type="checkbox" checked={recursive} onChange={event=>setRecursive(event.target.checked)}/>包含子目录</label><label><input type="checkbox" checked={realtime} onChange={event=>setRealtime(event.target.checked)}/>实时搜索（跳过索引）</label><button className="secondary" disabled={!features.search||!root||loading.has('root')}>搜索</button>{searchResult&&<button type="button" className="text-button" onClick={()=>root&&openRoot(root.path)}>清除搜索</button>}</form>
    {searchResult&&<p className="file-inline">使用 {searchResult.engine} 找到 {searchResult.entries.length} 项，已检查 {searchResult.scanned} 项。{searchResult.indexed?'索引可能滞后，可勾选实时搜索检查新文件。':'已实时查找。'}{searchResult.truncated?'达到时间、数量或层级限制，结果不完整，请缩小搜索范围。':''}{searchResult.skipped?'有 '+searchResult.skipped+' 项无法读取。':''}</p>}
    {searchResult?.locate_available===false&&<details className="file-search-install"><summary>这台机器未检测到 locate / plocate，正在使用实时搜索。查看加速搜索的安装方法</summary><p>请在这台远程机器的终端中执行对应命令（需要 sudo 权限）。</p>{[
      {label:'Ubuntu 22.04+ / Debian 12+',command:'sudo apt-get update && sudo apt-get install plocate && sudo updatedb'},
      {label:'Fedora',command:'sudo dnf install plocate && sudo updatedb'},
    ].map(item=><div key={item.label}><strong>{item.label}</strong><pre><code>{item.command}</code></pre><button type="button" className="text-button" onClick={()=>navigator.clipboard.writeText(item.command).then(()=>setMessage('安装命令已复制，请在远程终端中执行')).catch(()=>setError('复制失败，请手动选择并复制命令'))}>复制 {item.label} 命令</button></div>)}<p>首次建立索引可能需要一些时间；完成后重新搜索即可自动使用。索引可能不包含所有目录，也可能滞后。其他系统请按发行版安装 locate 工具；如果已经安装，请检查 SSH 会话的 PATH。</p></details>}
    <input type="file" multiple hidden ref={uploadInput} aria-label="选择上传文件" onChange={event=>{const files=Array.from(event.currentTarget.files||[]);event.currentTarget.value='';void upload(files)}}/>
    <div className="file-toolbar"><button className="secondary" title={currentDirectory} disabled={!features.upload||!currentDirectory||!!downloading||!!uploadRequest.current} onClick={()=>uploadInput.current?.click()}><Upload size={14}/>上传文件</button><button className="secondary" title={currentDirectory} disabled={!features.cwd||!currentDirectory} onClick={()=>{if(currentDirectory)onTerminal?.(currentDirectory)}}><Terminal size={14}/>在当前目录打开终端</button><button className="secondary" disabled={!supported||!currentDirectory||operationBusy} onClick={()=>setAction({op:'create',directory:currentDirectory!})}><FilePlus size={14}/>新建文件</button><button className="secondary" disabled={!supported||!currentDirectory||operationBusy} onClick={()=>setAction({op:'mkdir',directory:currentDirectory!})}><FolderPlus size={14}/>新建文件夹</button><button className="secondary" disabled={!supported||!selected||operationBusy} onClick={()=>stage(selected!,'copy')}><Copy size={14}/>复制</button><button className="secondary" disabled={!supported||!selected||operationBusy} onClick={()=>stage(selected!,'move')}><Scissors size={14}/>剪切</button><button className="secondary" disabled={!supported||!clipboard||!currentDirectory||operationBusy} onClick={()=>paste(currentDirectory!)}><ClipboardPaste size={14}/>粘贴到当前目录</button>{clipboard&&<span>{clipboard.op==='copy'?'复制':'剪切'}：{clipboard.entry.name}<button className="text-button" onClick={()=>setClipboard(null)}>取消</button></span>}{!supported&&<span>编辑与文件操作需重启本地服务启用</span>}</div>
    {transfer&&<div className="file-transfer" role="status"><div><strong>{transfer.direction==='upload'?'上传':'下载'}：{transfer.name}</strong><span>{{receiving:'浏览器 → 本地服务',sending:'本地服务 → 远端机器',verifying:'校验远端文件并发布',download_remote:'从远端接收文件',download_browser:'接收到浏览器',done:'传输完成'}[transfer.stage]}</span>{transfer.stage!=='done'&&<button className="text-button" onClick={cancelTransfer}>取消传输</button>}</div><progress max={Math.max(1,transfer.total??1)} value={transfer.total===null?undefined:transfer.stage==='done'?Math.max(1,transfer.total):transfer.loaded}/><small>{size(transfer.loaded)} / {transfer.total===null?'大小未知':size(transfer.total)}{transfer.stage==='done'?'':' · 关闭窗口或切换机器会取消传输'}</small></div>}
    {error&&<div role="alert" className="file-error">{error}</div>}{message&&<p role="status" className="file-inline">{message}</p>}
    <div className="file-tree" role="region" aria-label={host.target+' 目录树'} onScroll={()=>setMenu(null)}>{loading.has('root')?<p className="file-inline"><LoaderCircle size={16} className="spin"/>正在连接并读取目录…</p>:root&&<><div className="file-columns"><strong>{root.path}</strong><span>大小</span><span>修改时间</span></div>{children(root.path,0)}</>}</div>
    <footer className="file-footer">{downloading?<><LoaderCircle size={13} className="spin"/>正在下载，请稍候…</>:'使用当前 SSH 账号 · 文本编辑 ≤ 1 MiB · 复制 ≤ 64 MiB / 1000 项 · 下载 ≤ 512 MiB'}</footer>
    {menu&&<div className="file-context" ref={menuRef} role="menu" style={{left:menu.x,top:menu.y}}>
      {menu.entry.kind==='file'&&<><button role="menuitem" disabled={!supported} onClick={()=>edit(menu.entry)}>打开并编辑</button><button role="menuitem" disabled={!!downloading} onClick={()=>download(menu.entry)}><Download size={15}/>下载文件</button></>}
      {menu.entry.kind==='directory'&&<><button role="menuitem" onClick={()=>openRoot(menu.entry.path)}>进入目录</button><button role="menuitem" disabled={!features.cwd} onClick={()=>{onTerminal?.(menu.entry.path);setMenu(null)}}>在此处打开终端</button><button role="menuitem" disabled={!supported||!clipboard} onClick={()=>paste(menu.entry.path)}>粘贴到此目录</button></>}
      <button role="menuitem" disabled={!supported} onClick={()=>stage(menu.entry,'copy')}>复制</button><button role="menuitem" disabled={!supported} onClick={()=>stage(menu.entry,'move')}>剪切</button>
      <button role="menuitem" disabled={!supported} onClick={()=>{setAction({op:'move',source:menu.entry,directory:root!.path});setMenu(null)}}>移动到…</button>
      <button role="menuitem" disabled={!supported} onClick={()=>{setAction({op:'rename',source:menu.entry,directory:menu.entry.path.slice(0,menu.entry.path.lastIndexOf('/'))||'/'});setMenu(null)}}>重命名</button>
      <button role="menuitem" onClick={()=>copyPath(menu.entry)}>复制路径</button>
    </div>}
    {action&&<FileActionDialog action={action} close={()=>setAction(null)} submit={perform}/>}
    {editor&&<FileEditor key={editor} host={host.id} path={editor} close={()=>setEditor(null)} saved={()=>{if(root)void load(root.path)}} changed={()=>{}} busyChanged={setEditorBusy} closeRequest={editorClose}/>}

  </>;
}
