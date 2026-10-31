import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {downloadOriginalLog} from '../src/logDownload.ts';
import {fitFileWindow,moveFileWindow,resizeFileWindow} from '../src/fileWindow.ts';

function harness(t,component='BrowserBody',fetchDownload,folderSupported=true){
  const values=[],deps=[],effects=[],cleanups=[];let slot=0,tree;
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value}]},
    useRef:initial=>{const i=slot++;if(!(i in values))values[i]={current:initial};return values[i]},
    useEffect:(fn,next)=>{const i=slot++;if(!next||!deps[i]||next.some((v,j)=>v!==deps[i][j])){effects.push(()=>{cleanups[i]?.();cleanups[i]=fn()});deps[i]=next}}};
  const old={window:globalThis.window,document:globalThis.document,fetch:globalThis.fetch};
  Object.assign(globalThis,{window:{innerWidth:1200,innerHeight:800,addEventListener(){},removeEventListener(){}},document:{addEventListener(){},removeEventListener(){}},
    fetch:async(url,options)=>url==='/api/files/capabilities'?{ok:true,json:async()=>({editing:true,terminal_cwd:true,upload:true,search:true,folder_download:folderSupported})}:fetchDownload(url,options)});
  t.after(()=>{cleanups.splice(0).forEach(fn=>fn?.());Object.assign(globalThis,old)});
  const entries=['A','B'].map(name=>({name:name+'.txt',path:'/tmp/'+name+'.txt',kind:'file',accessible:true,size:1,modified:1}));
  entries.push({name:'code',path:'/tmp/code',kind:'directory',accessible:true,size:null,modified:1});
  const files={listDirectory:async(host,path)=>({path:path==='~'?'/tmp':path,parent:'/',entries:path==='~'||path==='/tmp'?entries:[],total:entries.length,next_offset:null}),fileOperation:async()=>({})};
  const exports={};
  const source=ts.transpileModule(fs.readFileSync(new URL('../src/FileBrowser.tsx',import.meta.url),'utf8')+'\nexport {BrowserBody};',
    {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  function FileEditor(){}
  new Function('require','exports',source)(name=>name==='react'?react:name==='./files'?files:name==='./logDownload'?{downloadOriginalLog}:name==='./fileWindow'?{fitFileWindow,moveFileWindow,resizeFileWindow}:name==='./FileEditor'?{FileEditor}:new Proxy({},{get:(_,key)=>key}),exports);
  const guard={current:null},hosts=[{id:'A',target:'A'},{id:'B',target:'B'}];
  let props=component==='BrowserBody'?{host:hosts[0],onBusy(){},editorClose:guard}:{host:hosts[0],hosts,close(){},requestId:'first'};
  const render=updates=>{props={...props,...updates};slot=0;tree=exports[component](props);for(const effect of effects.splice(0))effect();return tree};
  const nodes=node=>!node||typeof node!=='object'?[]:[node,...(node.props?.children||[]).flat(Infinity).flatMap(child=>nodes(child))];
  const find=predicate=>nodes(tree).find(predicate);
  return {render,find,guard,hosts,async loaded(){render();await new Promise(resolve=>setImmediate(resolve));render()},
    clickFile(name){find(n=>n.type==='button'&&n.props['aria-label']==='文件 /tmp/'+name+'.txt').props.onClick();render()},
    openFile(name){const button=()=>find(n=>n.type==='button'&&n.props['aria-label']==='文件 /tmp/'+name+'.txt');button().props.onClick();render();button().props.onClick();render();button().props.onDoubleClick();render()},
    editorPath(){return find(n=>n.type===FileEditor)?.props.path},body(){return find(n=>typeof n.type==='function'&&n.type.name==='BrowserBody')},
    unmount(){cleanups.splice(0).forEach(fn=>fn?.())}};
}

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
