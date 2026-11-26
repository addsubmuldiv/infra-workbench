import {i18nMock} from '../i18n-mock.mjs';
import * as toolTranslations from '../../src/shared/toolI18n.ts';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {downloadOriginalLog} from '../../src/features/files/logDownload.ts';
import {fitFileWindow,moveFileWindow,resizeFileWindow} from '../../src/features/files/fileWindow.ts';
import * as folderUploads from '../../src/features/files/folderUpload.ts';
import * as fileTransfers from '../../src/features/files/fileTransfers.ts';
import * as fileDrop from '../../src/features/files/fileDrop.ts';
import * as ids from '../../src/shared/browserId.ts';
import * as sshLogins from '../../src/features/hosts/sshLogins.ts';
import {setLocale} from '../../src/shared/i18n.ts';
import {workspaceStorage} from '../../src/workspace/workspaceState.ts';

function harness(t,component='BrowserBody',fetchDownload,folderSupported=true,folderSender,fileSender,uploadSupported=true,browse){
  const values=[],deps=[],effects=[],cleanups=[],listeners=new Map();let slot=0,tree;
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useMemo:factory=>factory(),
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value}]},
    useRef:initial=>{const i=slot++;if(!(i in values))values[i]={current:initial};return values[i]},
    useEffect:(fn,next)=>{const i=slot++;if(!next||!deps[i]||next.some((v,j)=>v!==deps[i][j])){effects.push(()=>{cleanups[i]?.();cleanups[i]=fn()});deps[i]=next}}};
  react.useLayoutEffect=react.useEffect;
  const old={window:globalThis.window,document:globalThis.document,fetch:globalThis.fetch};
  Object.assign(globalThis,{window:{innerWidth:1200,innerHeight:800,
      addEventListener(type,fn){listeners.set(type,[...(listeners.get(type)??[]),fn])},removeEventListener(type,fn){listeners.set(type,(listeners.get(type)??[]).filter(f=>f!==fn))}},
    document:{addEventListener(){},removeEventListener(){}},
    fetch:async(url,options)=>url==='/api/files/capabilities'?{ok:true,json:async()=>({editing:true,terminal_cwd:true,upload:uploadSupported,search:true,folder_download:folderSupported,folder_upload:folderSupported})}:fetchDownload(url,options)});
  t.after(()=>{cleanups.splice(0).forEach(fn=>fn?.());Object.assign(globalThis,old)});
  const entries=['A','B'].map(name=>({name:name+'.txt',path:'/tmp/'+name+'.txt',kind:'file',accessible:true,size:1,modified:1}));
  entries.push({name:'code',path:'/tmp/code',kind:'directory',accessible:true,size:null,modified:1});
  const files={listDirectory:async(host,path)=>({path:path==='~'?'/tmp':path,parent:'/',entries:await (browse?.(path)??(path==='~'||path==='/tmp'?entries:[])),total:entries.length,next_offset:null}),fileOperation:async()=>({})};
  const exports={};
  const source=ts.transpileModule(fs.readFileSync(new URL('../../src/features/files/FileBrowser.tsx',import.meta.url),'utf8')+'\nexport {BrowserBody};',
    {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  function FileEditor(){}
  new Function('require','exports',source)(name=>i18nMock(name)??((name==='../../shared/toolI18n'||name==='../../shared/toolI18n.ts')?toolTranslations:undefined)??(name==='react'?react:name==='../hosts/sshLogins'?sshLogins:name==='../../shared/browserId'?ids:name==='./files'?files:name==='./logDownload'?{downloadOriginalLog}:name==='./folderUpload'?folderUploads:name==='./fileDrop'?fileDrop:name==='./fileTransfers'?{...fileTransfers,uploadFile:fileSender??fileTransfers.uploadFile,uploadPayload:folderSender??fileTransfers.uploadPayload}:name==='./fileWindow'?{fitFileWindow,moveFileWindow,resizeFileWindow}:name==='./FileEditor'?{FileEditor}:new Proxy({},{get:(_,key)=>key})),exports);
  const guard={current:null},zone={current:null},hosts=[{id:'A',target:'A'},{id:'B',target:'B'}];
  let props=component==='BrowserBody'?{host:hosts[0],onBusy(){},editorClose:guard,dropZone:zone}:{host:hosts[0],hosts,close(){},requestId:'first'};
  const render=updates=>{props={...props,...updates};slot=0;tree=exports[component](props);for(const effect of effects.splice(0))effect();return tree};
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(child=>nodes(child))];
  const find=predicate=>nodes(tree).find(predicate);
  return {render,find,guard,zone,hosts,listeners,async loaded(){render();await new Promise(resolve=>setImmediate(resolve));render()},
    clickFile(name){find(n=>n.type==='button'&&n.props['aria-label']==='文件 /tmp/'+name+'.txt').props.onClick();render()},
    openFile(name){const button=()=>find(n=>n.type==='button'&&n.props['aria-label']==='文件 /tmp/'+name+'.txt');button().props.onClick();render();button().props.onClick();render();button().props.onDoubleClick();render()},
    editorPath(){return find(n=>n.type===FileEditor)?.props.path},body(){return find(n=>typeof n.type==='function'&&n.type.name==='BrowserBody')},
    unmount(){cleanups.splice(0).forEach(fn=>fn?.())}};
}
const feedback=h=>h.find(n=>n.props?.role==='status'&&n.props?.className==='file-inline')?.props.children;
const failure=h=>h.find(n=>n.props?.role==='alert')?.props.children?.join('');
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('the upload input sends each file to the selected directory in order and reports the count',{timeout:5000},async t=>{
  const calls=[];
  const h=harness(t,'BrowserBody',undefined,true,undefined,async(host,directory,file)=>{calls.push([host,directory,file.name]);return '/tmp/code/'+file.name});
  await h.loaded();h.find(n=>n.type==='button'&&n.props['aria-label']==='展开目录 /tmp/code').props.onClick();await h.loaded();
  h.find(n=>n.type==='input'&&n.props['aria-label']==='选择上传文件').props.onChange({currentTarget:{files:[new File(['a'],'a.txt'),new File(['b'],'b.txt')],value:'chosen'}});
  await settle();h.render();
  assert.deepEqual(calls,[['A','/tmp/code','a.txt'],['A','/tmp/code','b.txt']]);
  assert.equal(feedback(h).join(''),'已上传 2 个文件到 /tmp/code');
});

// File and Directory Entries API shapes for one dropped folder holding a nested file and an empty directory.
function directory(name,children=[]){let offset=0;return{isDirectory:true,isFile:false,name,
  createReader(){return{readEntries(done){const batch=children.slice(offset,offset+100);offset+=batch.length;done(batch)}}}}}
function leaf(name,raw){return{isDirectory:false,isFile:true,name,file(done){done(new File([raw],name))}}}
// A drop carrying one text file and one folder, exposed the way DataTransferItem exposes dropped items.
const dropped=()=>fileDrop.collectDrop({items:[
  {kind:'file',webkitGetAsEntry:()=>({isFile:true,isDirectory:false,name:'a.txt'}),getAsFile:()=>new File(['a'],'a.txt')},
  {kind:'string'},
  {kind:'file',webkitGetAsEntry:()=>directory('project',[directory('sub',[leaf('b.bin','bytes')]),directory('empty')]),getAsFile:()=>null},
]});
// Opens /tmp/code so it becomes the current directory; the label is matched by path so either interface language works.
const openCode=async h=>{await h.loaded();h.find(n=>n.type==='button'&&n.props['aria-label']?.endsWith('/tmp/code')).props.onClick();await h.loaded()};

test('a drop uploads its files and then its folders to the selected directory as one cancellable batch',{timeout:5000},async t=>{
  const calls=[],bodies=[];let signal,sent=0;
  // Every folder upload completes; the second file upload waits until its batch is cancelled.
  const h=harness(t,'BrowserBody',undefined,true,
    (host,directory,name,body,kind)=>{calls.push(['folder',host,directory,name,kind]);bodies.push(body);return Promise.resolve('/tmp/code/'+name)},
    async(host,directory,file,s,progress)=>{
      calls.push(['file',host,directory,file.name]);
      if(++sent!==2)return '/tmp/code/'+file.name;
      signal=s;progress({stage:'receiving',loaded:0,total:file.size});
      return new Promise((resolve,reject)=>{s.addEventListener('abort',()=>reject(new DOMException('cancel','AbortError')),{once:true})});
    });
  await openCode(h);
  assert.equal(h.zone.current?.state,'ready');assert.equal(h.zone.current?.directory,'/tmp/code');
  const uploadButton=()=>h.find(n=>n.type==='button'&&n.props.children.includes('上传文件'));
  const task=h.zone.current.upload(dropped());h.render();
  assert.equal(uploadButton().props.disabled,true);
  await task;h.render();
  assert.deepEqual(calls,[['file','A','/tmp/code','a.txt'],['folder','A','/tmp/code','project','folder']]);
  const payload=await bodies[0].text();
  assert.ok(payload.includes('"path":"sub/b.bin"'));assert.ok(payload.includes('"directories":["empty","sub"]'));assert.ok(payload.endsWith('bytes'));
  assert.equal(feedback(h).join(''),'已上传 1 个文件、1 个文件夹到 /tmp/code');assert.equal(uploadButton().props.disabled,false);
  // Cancelling the visible transfer aborts the file in flight; the folder queued behind it is never started.
  const cancelled=h.zone.current.upload(dropped());await settle();h.render();
  h.find(n=>n.type==='button'&&n.props.children.includes('取消传输')).props.onClick();
  assert.equal(signal.aborted,true);
  await cancelled;h.render();
  assert.match(feedback(h).join(''),/取消/);assert.equal(calls.length,3);assert.equal(uploadButton().props.disabled,false);
});

const text=name=>({kind:'file',name,file:new File(['x'],name)});
const uploadButton=h=>h.find(n=>n.type==='button'&&n.props.children.includes('上传文件'));

test('a failed item stops the dropped batch and names it in the error',{timeout:5000},async t=>{
  const calls=[],reads=[];
  const h=harness(t,'BrowserBody',undefined,true,undefined,async(host,directory,file)=>{
    calls.push(file.name);if(file.name==='b.txt')throw new Error('远端空间不足');return '/tmp/code/'+file.name},true,path=>{reads.push(path)});
  await openCode(h);
  await h.zone.current.upload(['a.txt','b.txt','c.txt'].map(text));h.render();
  assert.deepEqual(calls,['a.txt','b.txt']);assert.equal(failure(h),'已上传 1/3 项到 /tmp/code。[2/3] b.txt：远端空间不足');
  assert.deepEqual(reads,['~','/tmp/code','/tmp/code']);
  assert.equal(feedback(h),undefined);assert.equal(uploadButton(h).props.disabled,false);
  // The destination is unchanged, so a retry after fixing the cause lands in the same directory.
  assert.equal(h.zone.current.directory,'/tmp/code');assert.equal(h.zone.current.state,'ready');
});

test('a drop uses the hovered directory without changing the current directory and blocks while navigating',async t=>{
  const sent=[];let release;
  const h=harness(t,'BrowserBody',undefined,true,undefined,async(host,directory,file)=>{sent.push([directory,file.name])},true,
    path=>path==='/other'?new Promise(resolve=>{release=()=>resolve([])}):undefined);
  await h.loaded();
  await h.zone.current.upload([text('a.txt')],'/tmp/code');
  h.render();assert.equal(h.zone.current.directory,'/tmp');
  h.find(n=>n.props?.['aria-label']==='服务器目录路径').props.onChange({target:{value:'/other'}});h.render();
  h.find(n=>n.props?.className==='file-path').props.onSubmit({preventDefault(){}});
  assert.equal(h.zone.current.state,'unavailable');
  await h.zone.current.upload([text('blocked.txt')],'/tmp/code');
  release();await settle();h.render();
  await h.zone.current.upload([text('b.txt')]);
  assert.deepEqual(sent,[['/tmp/code','a.txt'],['/other','b.txt']]);
});

test('a drop is refused without sending anything when the environment cannot upload',{timeout:5000},async t=>{
  const calls=[];
  const h=harness(t,'BrowserBody',undefined,true,undefined,async(host,directory,file)=>{calls.push(file.name);return '/tmp/code/'+file.name},false);
  await openCode(h);
  assert.equal(h.zone.current.state,'unsupported');
  await h.zone.current.upload(dropped());h.render();
  assert.deepEqual(calls,[]);assert.equal(failure(h),undefined);assert.equal(feedback(h),undefined);
});

test('a drop holding folders is refused as a whole while folder upload is unavailable',{timeout:5000},async t=>{
  const calls=[];
  const h=harness(t,'BrowserBody',undefined,false,undefined,async(host,directory,file)=>{calls.push(file.name);return '/tmp/code/'+file.name});
  await openCode(h);
  assert.equal(h.zone.current.state,'ready');
  await h.zone.current.upload(dropped());h.render();
  assert.deepEqual(calls,[]);assert.equal(failure(h),'重启本地服务以启用文件夹上传');
});

test('a drop waits without sending anything while another transfer is active',{timeout:5000},async t=>{
  const calls=[];let started;const pending=new Promise(resolve=>{started=resolve});
  const h=harness(t,'BrowserBody',(url,options)=>new Promise((resolve,reject)=>{started();options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true})}),
    true,undefined,async(host,directory,file)=>{calls.push(file.name);return '/tmp/code/'+file.name});
  await h.loaded();
  const download=h.find(n=>n.type==='button'&&n.props['aria-label']==='下载 /tmp/A.txt').props.onClick();
  await pending;h.render();
  assert.equal(h.zone.current.state,'busy');
  await h.zone.current.upload([text('a.txt')]);h.render();
  assert.deepEqual(calls,[]);assert.equal(failure(h),undefined);assert.equal(feedback(h),undefined);
  h.unmount();await download;
});

test('closing the file window aborts a dropped batch that is still in flight',{timeout:5000},async t=>{
  const calls=[];let signal,started;const pending=new Promise(resolve=>{started=resolve});
  const h=harness(t,'BrowserBody',undefined,true,undefined,(host,directory,file,s)=>{
    calls.push(file.name);signal=s;started();return new Promise((resolve,reject)=>{s.addEventListener('abort',()=>reject(s.reason),{once:true})})});
  await openCode(h);
  const task=h.zone.current.upload([text('a.txt'),text('b.txt')]);await pending;
  assert.equal(signal.aborted,false);h.unmount();assert.equal(signal.aborted,true);
  await task;assert.deepEqual(calls,['a.txt']);
});

// Drag events as the file window receives them. `target` is the element under the pointer; the window itself is the frame.
const FRAME={contains:()=>true};
const item=(name,entry=null)=>({kind:'file',webkitGetAsEntry:()=>entry,getAsFile:()=>new File(['x'],name)});
const drag=(types=['Files'],target={closest:()=>null},items=[item('a.txt'),item('project',directory('project'))])=>({target,currentTarget:FRAME,
  dataTransfer:{types,items:types.includes('Files')?items:[],dropEffect:'copy'},prevented:0,preventDefault(){this.prevented++}});
const pane=h=>h.find(n=>n.props?.className?.startsWith('file-browser floating'));
const hint=h=>h.find(n=>n.props?.className?.startsWith('file-drop'));
const words=node=>typeof node==='string'?[node]:!node||typeof node!=='object'?[]:(node.props?.children||[]).flat(Infinity).flatMap(words);
const targetZone=(h,state,directory,uploads=[],errors=[])=>{h.body().props.dropZone.current={state,directory,
  upload:(items,target)=>uploads.push({items,target}),reportError:error=>errors.push(error)}};

test('dragging files over the file window names the target directory, and dropping hands the items to the upload',t=>{
  const h=harness(t,'FileBrowser');h.render();
  const uploads=[];targetZone(h,'ready','/tmp/code',uploads);
  pane(h).props.onDragEnter(drag());h.render();
  assert.equal(words(hint(h)).join(''),'松开鼠标，上传 2 项到 /tmp/code');
  const over=drag();pane(h).props.onDragOver(over);assert.equal(over.prevented,1);assert.equal(over.dataTransfer.dropEffect,'copy');
  const drop=drag();pane(h).props.onDrop(drop);h.render();
  assert.equal(drop.prevented,1);assert.equal(hint(h),undefined);
  assert.equal(uploads[0].target,'/tmp/code');
  assert.deepEqual(uploads[0].items.map(i=>[i.kind,i.name]),[['file','a.txt'],['directory','project']]);
  // A single item is announced without a count.
  pane(h).props.onDragEnter(drag(['Files'],{closest:()=>null},[item('only.txt')]));h.render();
  assert.equal(words(hint(h)).join(''),'松开鼠标，上传到 /tmp/code');
});

test('the hover hint survives crossing child elements and clears when the drag leaves the window',t=>{
  const h=harness(t,'FileBrowser');h.render();targetZone(h,'ready','/tmp');
  pane(h).props.onDragEnter(drag());h.render();
  pane(h).props.onDragLeave({...drag(),relatedTarget:drag().target});h.render();assert.ok(hint(h));
  pane(h).props.onDragLeave({...drag(),relatedTarget:null});h.render();assert.equal(hint(h),undefined);
  // Drags without files, such as selected text, keep the browser's default handling.
  const text=drag(['text/plain']);pane(h).props.onDragEnter(text);pane(h).props.onDragOver(text);pane(h).props.onDrop(text);h.render();
  assert.equal(text.prevented,0);assert.equal(hint(h),undefined);
});

test('directory rows preview the explicit destination, and inaccessible or unreadable drops never upload',t=>{
  const h=harness(t,'FileBrowser');h.render();const uploads=[],errors=[];
  targetZone(h,'ready','/tmp',uploads,errors);
  const row=path=>({closest:selector=>selector==='[data-file-drop-directory]'?{getAttribute:()=>path}:null});
  const project=drag(['Files'],row('/tmp/project'));
  pane(h).props.onDragOver(project);h.render();
  assert.equal(words(hint(h)).join(''),'松开鼠标，上传 2 项到 /tmp/project');
  assert.equal(h.body().props.dropDirectory,'/tmp/project');
  pane(h).props.onDrop(project);h.render();assert.equal(uploads[0].target,'/tmp/project');
  const locked=drag(['Files'],row(''));
  pane(h).props.onDragOver(locked);h.render();assert.deepEqual(words(hint(h)),['无法访问此目录']);
  pane(h).props.onDrop(locked);assert.equal(uploads.length,1);
  pane(h).props.onDrop(drag(['Files'],row('/tmp/project'),[item('ok'),{kind:'file',getAsFile:()=>null}]));
  assert.equal(uploads.length,1);assert.match(errors[0],/无法读取拖入的项目/);
});

test('the hint explains why a drop is refused, and a refused drop uploads nothing',t=>{
  const h=harness(t,'FileBrowser');h.render();const uploads=[];
  targetZone(h,'busy','/tmp',uploads);pane(h).props.onDragEnter(drag());h.render();
  assert.deepEqual(words(hint(h)),['有传输正在进行，完成后再拖放上传']);
  const over=drag();pane(h).props.onDragOver(over);assert.equal(over.dataTransfer.dropEffect,'none');
  pane(h).props.onDrop(drag());assert.deepEqual(uploads,[]);
  for(const [state,text] of [['unsupported','当前环境不支持上传'],['unavailable','目录尚未加载，暂时无法上传']]){
    targetZone(h,state,undefined,uploads);pane(h).props.onDragOver(drag());h.render();
    assert.deepEqual(words(hint(h)),[text]);
  }
  pane(h).props.onDrop(drag());assert.deepEqual(uploads,[]);
  // The hint follows the browser body: a transfer that finished mid-drag turns the same hover into a valid target.
  targetZone(h,'ready','/tmp',uploads);pane(h).props.onDragOver(drag());h.render();
  assert.equal(words(hint(h)).join(''),'松开鼠标，上传 2 项到 /tmp');
});

test('a minimized file window still announces its drop target on the bar',t=>{
  const h=harness(t,'FileBrowser');h.render();targetZone(h,'ready','/tmp/code');
  h.find(n=>n.type==='button'&&n.props['aria-label']==='最小化文件窗口').props.onClick();h.render();
  pane(h).props.onDragEnter(drag());h.render();
  assert.equal(words(hint(h)).join(''),'松开鼠标，上传 2 项到 /tmp/code');assert.equal(pane(h).props.className.includes('minimized'),true);
});

test('drops on the editor above the file browser or elsewhere on the page never upload or navigate',t=>{
  const h=harness(t,'FileBrowser');h.render();const uploads=[];targetZone(h,'ready','/tmp',uploads);
  for(const layer of ['file-editor floating','file-context','file-confirm-shade']){
    const event=drag(['Files'],{closest:()=>({className:layer})});
    pane(h).props.onDragEnter(event);pane(h).props.onDragOver(event);pane(h).props.onDrop(event);h.render();
    assert.equal(event.prevented,0,layer);assert.equal(hint(h),undefined,layer);
  }
  assert.deepEqual(uploads,[]);
  // The page-level guard keeps the browser from opening a file dropped outside the file window.
  const [dragover]=h.listeners.get('dragover'),[drop]=h.listeners.get('drop');assert.ok(dragover&&drop);
  const stray=drag();dragover(stray);
  assert.equal(stray.prevented,1);assert.equal(stray.dataTransfer.dropEffect,'none');
  const link=drag(['text/uri-list','text/html']);dragover(link);drop(link);assert.equal(link.prevented,0);
  // A drag that moved on without a matching dragleave cannot leave a stale hint behind.
  pane(h).props.onDragEnter(drag());h.render();assert.ok(hint(h));
  dragover(drag());h.render();assert.equal(hint(h),undefined);
  pane(h).props.onDragEnter(drag());h.render();assert.ok(hint(h));
  drop(drag());h.render();assert.equal(hint(h),undefined);
  h.unmount();assert.deepEqual(h.listeners.get('dragover'),[]);assert.deepEqual(h.listeners.get('drop'),[]);
});

test('file operation feedback disappears after four seconds and new feedback restarts the timer',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const h=harness(t);await h.loaded();
  const copy=()=>h.find(n=>n.type==='button'&&n.props.children.includes('复制')).props.onClick();
  const message=()=>h.find(n=>n.props?.className==='file-inline'&&n.props?.role==='status');
  h.clickFile('A');copy();h.render();assert.ok(message());
  t.mock.timers.tick(3000);h.clickFile('B');copy();h.render();
  t.mock.timers.tick(1000);h.render();assert.ok(message());
  t.mock.timers.tick(3000);h.render();assert.equal(message(),undefined);
});

test('switching files preserves the old editor until the save guard permits leaving',async t=>{
  const h=harness(t);await h.loaded();h.openFile('A');assert.equal(h.editorPath(),'/tmp/A.txt');
  let proceed,guards=0;h.guard.current=after=>{guards++;proceed=after};
  h.openFile('A');assert.equal(guards,0);
  h.clickFile('B');assert.equal(guards,0);assert.equal(h.editorPath(),'/tmp/A.txt');
  h.openFile('B');assert.equal(guards,1);assert.equal(h.editorPath(),'/tmp/A.txt');
  proceed();h.render();assert.equal(h.editorPath(),'/tmp/B.txt');
});

test('single click selects a file for copy without opening an editor; double click edits it',async t=>{
  const h=harness(t);await h.loaded();h.clickFile('A');assert.equal(h.editorPath(),undefined);
  const copy=h.find(n=>n.type==='button'&&n.props.children.includes('复制'));
  assert.equal(copy.props.disabled,false);copy.props.onClick();h.render();
  h.find(n=>n.type==='button'&&n.props.children.includes('粘贴到当前目录')).props.onClick();h.render();
  assert.equal(h.find(n=>n.props?.action)?.props.action.source.path,'/tmp/A.txt');
  h.openFile('A');assert.equal(h.editorPath(),'/tmp/A.txt');
});

test('selecting a tree directory synchronizes the path and terminal and creation targets',async t=>{
  const h=harness(t),opened=[];await h.loaded();h.render({onTerminal:path=>opened.push(path)});
  h.find(n=>n.type==='button'&&n.props['aria-label']==='展开目录 /tmp/code').props.onClick();h.render();
  assert.equal(h.find(n=>n.type==='input'&&n.props['aria-label']==='服务器目录路径').props.value,'/tmp/code');
  const terminal=()=>h.find(n=>n.type==='button'&&n.props.children.includes('在当前目录打开终端'));
  terminal().props.onClick();assert.deepEqual(opened,['/tmp/code']);
  h.find(n=>n.type==='button'&&n.props.children.includes('新建文件')).props.onClick();h.render();
  assert.equal(h.find(n=>n.props?.action)?.props.action.directory,'/tmp/code');
  // Unsubmitted address-bar input must not change the directory used by actions.
  h.find(n=>n.type==='input'&&n.props['aria-label']==='服务器目录路径').props.onChange({target:{value:'/not-submitted'}});h.render();
  terminal().props.onClick();assert.deepEqual(opened,['/tmp/code','/tmp/code']);
  // Explicit navigation replaces the old selection as well as the tree root.
  h.find(n=>n.type==='button'&&n.props['aria-label']==='刷新文件目录').props.onClick();await h.loaded();
  assert.equal(h.find(n=>n.type==='input'&&n.props['aria-label']==='服务器目录路径').props.value,'/tmp/code');
  h.find(n=>n.type==='button'&&n.props['aria-label']==='打开主目录').props.onClick();await h.loaded();
  terminal().props.onClick();assert.equal(opened.at(-1),'/tmp');
});

test('external machine requests respect cancellation and wait until an active save finishes',t=>{
  const h=harness(t,'FileBrowser');h.render();let proceed;
  h.body().props.editorClose.current=after=>{proceed=after};
  h.render({host:h.hosts[1],requestId:'second'});assert.equal(h.body().props.host.id,'A');
  // Cancel: leave the callback unused, and allow a later explicit request to retry.
  h.render({requestId:'third'});assert.equal(h.body().props.host.id,'A');
  proceed();h.render();assert.equal(h.body().props.host.id,'B');
  h.body().props.onBusy(true);h.render();
  proceed=null;h.render({host:h.hosts[0],requestId:'fourth'});assert.equal(proceed,null);
  h.body().props.onBusy(false);h.render();assert.equal(typeof proceed,'function');
  proceed();h.render();assert.equal(h.body().props.host.id,'A');
});

test('closing the file browser aborts its unfinished download',async t=>{
  let signal,started;const pending=new Promise(resolve=>{started=resolve});
  const h=harness(t,'BrowserBody',(url,options)=>new Promise((resolve,reject)=>{
    signal=options.signal;started();signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
  }));
  await h.loaded();const download=h.find(n=>n.type==='button'&&n.props['aria-label']==='下载 /tmp/A.txt').props.onClick();
  await pending;assert.equal(signal.aborted,false);h.unmount();assert.equal(signal.aborted,true);await download;
});

test('folder menu downloads the selected folder through the archive endpoint and can cancel',async t=>{
  let request,started;const pending=new Promise(resolve=>started=resolve);
  const h=harness(t,'BrowserBody',(url,options)=>new Promise((resolve,reject)=>{
    request={url,...options};started();options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
  }));
  await h.loaded();
  h.find(n=>n.type==='button'&&n.props['aria-label']==='文件操作 /tmp/code').props.onClick({preventDefault(){},clientX:100,clientY:100});h.render();
  const download=h.find(n=>n.props?.role==='menuitem'&&n.props.children.includes('下载文件夹'));
  assert.ok(download);assert.equal(download.props.disabled,false);
  const task=download.props.onClick();await pending;
  assert.equal(request.url,'/api/files/download-folder');assert.equal(JSON.parse(request.body).path,'/tmp/code');
  h.unmount();assert.equal(request.signal.aborted,true);await task;
});

test('old backends expose the folder action as disabled until upgraded',async t=>{
  const h=harness(t,'BrowserBody',undefined,false);await h.loaded();
  h.find(n=>n.type==='button'&&n.props['aria-label']==='文件操作 /tmp/code').props.onClick({preventDefault(){},clientX:100,clientY:100});h.render();
  assert.equal(h.find(n=>n.props?.role==='menuitem'&&n.props.children.includes('下载文件夹')).props.disabled,true);
  assert.equal(h.find(n=>n.type==='button'&&n.props.children.includes('上传文件夹')).props.disabled,true);
});

test('folder picker preserves the selected destination and passes one cancellable bundle to upload',async t=>{
  let actual,signal,started;const pending=new Promise(resolve=>started=resolve);
  const h=harness(t,'BrowserBody',undefined,true,(...args)=>new Promise((resolve,reject)=>{
    actual=args;signal=args[5];started();signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
  }));
  await h.loaded();h.find(n=>n.type==='button'&&n.props['aria-label']==='展开目录 /tmp/code').props.onClick();await h.loaded();
  const file=new File(['contents'],'a.txt');Object.defineProperty(file,'webkitRelativePath',{value:'project/sub/a.txt'});
  const input=h.find(n=>n.type==='input'&&n.props['aria-label']==='上传文件夹选择器');assert.ok(input);assert.equal(input.props.webkitdirectory,'');
  input.props.onChange({currentTarget:{files:[file],value:'selected'}});await pending;h.render();
  assert.deepEqual(actual.slice(0,3),['A','/tmp/code','project']);assert.equal(actual[4],'folder');assert.ok(actual[3] instanceof Blob);
  h.find(n=>n.type==='button'&&n.props.children.includes('取消传输')).props.onClick();assert.equal(signal.aborted,true);
  await new Promise(resolve=>setImmediate(resolve));h.render();
});

test('native folder chooser uploads empty directories and a closed window cannot start a late upload',async t=>{
  const uploads=[];
  const h=harness(t,'BrowserBody',undefined,true,async(...args)=>{uploads.push(args);return '/tmp/empty-project'});await h.loaded();
  window.showDirectoryPicker=async()=>({kind:'directory',name:'empty-project',async *entries(){yield ['empty',{kind:'directory',name:'empty',async *entries(){}}]}});
  h.find(n=>n.type==='button'&&n.props.children.includes('上传文件夹')).props.onClick();
  await new Promise(resolve=>setImmediate(resolve));h.render();
  assert.equal(uploads.length,1);assert.equal(uploads[0][2],'empty-project');
  assert.ok((await uploads[0][3].text()).includes('"directories":["empty"]'));
  let choose;window.showDirectoryPicker=()=>new Promise(resolve=>choose=resolve);
  h.find(n=>n.type==='button'&&n.props.children.includes('上传文件夹')).props.onClick();h.unmount();
  choose({kind:'directory',name:'late',async *entries(){}});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(uploads.length,1);
});

test('terminal path requests reopen a minimized file window and keep unsaved edits guarded',t=>{
  const h=harness(t,'FileBrowser');h.render();let proceed;
  h.find(n=>n.type==='button'&&n.props['aria-label']==='最小化文件窗口').props.onClick();h.render();
  h.body().props.editorClose.current=after=>{proceed=after};
  h.render({host:h.hosts[0],requestId:'pwd-link',initialPath:'/data/训练 项目'});
  assert.equal(h.body().props.navigation.path,'~');
  assert.ok(h.find(n=>n.type==='button'&&n.props['aria-label']==='恢复文件窗口'));
  proceed();h.render();assert.equal(h.body().props.navigation.path,'/data/训练 项目');
  assert.ok(h.find(n=>n.type==='button'&&n.props['aria-label']==='最小化文件窗口'));
});

test('file browser edges resize the actual window and maximize restores its frame',t=>{
  const h=harness(t,'FileBrowser');h.render();
  const pane=()=>h.find(n=>n.props?.className?.startsWith('file-browser floating'));
  const edge=()=>h.find(n=>n.props?.className==='file-edge-resize edge-e');
  const original={...pane().props.style};
  const event={button:0,pointerId:1,clientX:100,clientY:100,target:{closest:()=>null},currentTarget:{setPointerCapture(){}},preventDefault(){}};
  edge().props.onPointerDown(event);pane().props.onPointerMove({...event,clientX:180});h.render();
  assert.equal(pane().props.style.width,original.width+80);assert.equal(pane().props.style.left,original.left);
  pane().props.onPointerUp(event);
  const resized={...pane().props.style};
  h.find(n=>n.props?.['aria-label']==='最大化文件窗口').props.onClick();h.render();assert.equal(pane().props.style.width,1184);
  h.find(n=>n.props?.['aria-label']==='还原文件窗口').props.onClick();h.render();assert.deepEqual(pane().props.style,resized);
});

test('drop hints read as English under the English interface',t=>{
  try{setLocale('en');
    const h=harness(t,'FileBrowser');h.render();targetZone(h,'ready','/tmp/code');
    pane(h).props.onDragEnter(drag());h.render();
    assert.equal(words(hint(h)).join(''),'Release to upload 2 items to /tmp/code');
    for(const [state,text] of [['busy','A transfer is in progress. Drop files again once it finishes'],['unsupported','Uploads are unavailable in this environment'],['unavailable','The directory has not loaded yet, so nothing can be uploaded']]){
      targetZone(h,state);pane(h).props.onDragOver(drag());h.render();assert.deepEqual(words(hint(h)),[text]);
    }
  }finally{setLocale('zh');workspaceStorage.dispose()}
});

test('drop results and errors read as English under the English interface',{timeout:5000},async t=>{
  try{setLocale('en');
    const h=harness(t,'BrowserBody',undefined,true,async(host,directory,name)=>'/tmp/code/'+name,
      async(host,directory,file)=>{if(file.name==='b.txt')throw new Error('Disk full');return '/tmp/code/'+file.name});
    await openCode(h);
    await h.zone.current.upload(dropped());h.render();
    assert.equal(feedback(h).join(''),'Uploaded 1 file and 1 folder to /tmp/code');
    await h.zone.current.upload(['a.txt','b.txt'].map(text));h.render();
    assert.equal(failure(h),'Uploaded 1/2 items to /tmp/code. [2/2] b.txt: Disk full');
  }finally{setLocale('zh');workspaceStorage.dispose()}
});
