import test from 'node:test';
import assert from 'node:assert/strict';
import {dragHasFiles,collectDrop,droppedFolder,overFileWindow,watchFileDrop} from '../../src/features/files/fileDrop.ts';
import {readFolder} from '../../src/features/files/folderUpload.ts';

// File and Directory Entries API shapes as Chromium exposes them for dropped items.
function folder(name,children=[]){let offset=0;return{isDirectory:true,isFile:false,name,
  createReader(){return{readEntries(done){const batch=children.slice(offset,offset+100);offset+=batch.length;done(batch)}}}}}
function leaf(name,raw='data'){return{isDirectory:false,isFile:true,name,file(done){done(new File([raw],name))}}}

test('only drags that carry files are treated as upload drops',()=>{
  assert.equal(dragHasFiles({types:['Files']}),true);
  assert.equal(dragHasFiles({types:['text/plain','text/html']}),false);
  // Older WebKit exposes DOMStringList instead of a frozen array.
  assert.equal(dragHasFiles({types:{contains:type=>type==='Files',length:1,0:'Files'}}),true);
  assert.equal(dragHasFiles(undefined),false);assert.equal(dragHasFiles({}),false);
});

test('a drop is collected synchronously into files and directories and ignores other data',()=>{
  const a=new File(['a'],'a.txt'),project={isDirectory:true,isFile:false,name:'project'};
  const plain={kind:'file',webkitGetAsEntry:()=>null,getAsFile:()=>a},folder={kind:'file',webkitGetAsEntry:()=>project,getAsFile:()=>null};
  const drop=collectDrop({items:{length:3,0:{kind:'string'},1:folder,2:plain},files:[]});
  assert.deepEqual(drop.map(item=>[item.kind,item.name]),[['directory','project'],['file','a.txt']]);
  assert.equal(drop[0].entry,project);assert.equal(drop[1].file,a);
  // A directory without a readable entry must not be uploaded as a phantom empty file.
  const hidden={kind:'file',webkitGetAsEntry:()=>({isFile:false,isDirectory:true,name:'hidden'}),getAsFile:()=>new File([],'hidden')};
  assert.deepEqual(collectDrop({items:[hidden],files:[]}).map(item=>item.kind),['directory']);
});

test('plain files are used when the browser exposes no draggable items',()=>{
  const a=new File(['a'],'a.txt');
  assert.deepEqual(collectDrop({files:{length:1,0:a}}).map(item=>[item.kind,item.name,item.file]),[['file','a.txt',a]]);
  assert.deepEqual(collectDrop(null),[]);assert.deepEqual(collectDrop({items:[],files:[]}),[]);
});

test('a dropped folder is read in batches so listings beyond 100 entries stay complete',async()=>{
  const root=folder('project',[...Array.from({length:250},(_,i)=>leaf('f'+i,'x')),folder('sub',[leaf('a.bin','bytes')]),folder('empty')]);
  const counts=[],selection=await readFolder(droppedFolder(root),new AbortController().signal,count=>counts.push(count));
  assert.equal(selection.name,'project');assert.equal(selection.files.length,251);assert.equal(selection.preservesEmpty,true);
  assert.deepEqual(selection.files.filter(f=>f.path.includes('/')).map(f=>[f.path,f.file.size]),[['sub/a.bin',5]]);
  assert.deepEqual(selection.directories,['empty','sub']);assert.equal(Math.max(...counts),253);
});

test('unreadable dropped folders fail with the browser error instead of uploading a partial tree',async()=>{
  const failure=new DOMException('denied','NotReadableError');
  const locked={isDirectory:true,isFile:false,name:'locked',createReader(){return{readEntries(done,fail){setTimeout(()=>fail(failure),0)}}}};
  await assert.rejects(readFolder(droppedFolder(locked),new AbortController().signal),error=>error===failure);
  const unsupported={isDirectory:true,isFile:false,name:'plain'};
  await assert.rejects(readFolder(droppedFolder(unsupported),new AbortController().signal),/无法读取拖入的文件夹/);
});

test('files dropped outside the file window are cancelled so the browser does not open them',()=>{
  const listeners=new Map(),calls=[];
  const surface={addEventListener(type,fn){listeners.set(type,[...(listeners.get(type)??[]),fn])},
    removeEventListener(type,fn){listeners.set(type,(listeners.get(type)??[]).filter(f=>f!==fn))}};
  const stop=watchFileDrop(surface,{leave:()=>calls.push('leave')});
  const [dragover]=listeners.get('dragover'),[drop]=listeners.get('drop');assert.ok(dragover&&drop);
  // `handled` marks an event the file window already accepted and cancelled itself.
  const event=(types,handled)=>({dataTransfer:{types,dropEffect:'copy'},defaultPrevented:handled,
    preventDefault(){calls.push('prevent');this.defaultPrevented=true}});
  const stray=event(['Files'],false);dragover(stray);
  assert.deepEqual(calls,['prevent','leave']);assert.equal(stray.dataTransfer.dropEffect,'none');
  calls.length=0;const own=event(['Files'],true);dragover(own);
  assert.deepEqual(calls,[]);assert.equal(own.dataTransfer.dropEffect,'copy');
  for(const listener of [dragover,drop]){const link=event(['text/uri-list','text/html'],false);listener(link);assert.equal(link.defaultPrevented,false)}
  calls.length=0;drop(event(['Files'],false));assert.deepEqual(calls,['prevent','leave']);
  calls.length=0;drop(event(['Files'],true));assert.deepEqual(calls,['leave']);
  stop();assert.deepEqual(listeners.get('dragover'),[]);assert.deepEqual(listeners.get('drop'),[]);
});

test('drops on windows layered above the file browser stay outside the drop zone',()=>{
  const frame={contains:target=>target.owner==='file'},target=(owner,layer)=>({owner,closest:()=>layer?{className:layer}:null});
  assert.equal(overFileWindow(frame,target('file')),true);
  for(const layer of ['file-editor','file-context','file-confirm-shade'])assert.equal(overFileWindow(frame,target('file',layer)),false);
  assert.equal(overFileWindow(frame,target('page')),false);assert.equal(overFileWindow(null,target('file')),false);
  assert.equal(overFileWindow(frame,null),false);assert.equal(overFileWindow(frame,{owner:'file'}),false);
});
