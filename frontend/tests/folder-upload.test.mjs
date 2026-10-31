import test from 'node:test';
import assert from 'node:assert/strict';
import {folderFromFiles,readFolder,folderPayload} from '../src/folderUpload.ts';
import {uploadPayload} from '../src/fileTransfers.ts';

function file(path,raw='data'){
  const value=new File([raw],path.split('/').at(-1));Object.defineProperty(value,'webkitRelativePath',{value:path});return value;
}
function directory(name,children=[]){return {kind:'directory',name,async *entries(){for(const child of children)yield [child.name,child]}}}
function handle(name,raw){return {kind:'file',name,async getFile(){return new File([raw],name)}}}

test('folder input preserves relative tree and binary content without flattening filenames',async()=>{
  const selection=folderFromFiles([file('project/sub/中文.bin',new Uint8Array([0,255,10])),file('project/.hidden','hidden')]);
  const payload=folderPayload(selection),raw=new Uint8Array(await payload.arrayBuffer());
  const first=raw.indexOf(10),second=raw.indexOf(10,first+1);
  assert.equal(new TextDecoder().decode(raw.slice(0,first)),'IWB_FOLDER:1');
  const manifest=JSON.parse(new TextDecoder().decode(raw.slice(first+1,second)));
  assert.deepEqual(manifest.files.map(f=>f.path),['sub/中文.bin','.hidden']);assert.deepEqual(manifest.directories,['sub']);
  assert.deepEqual([...raw.slice(second+1,second+4)],[0,255,10]);assert.equal(selection.name,'project');
  assert.equal(selection.preservesEmpty,false);
});

test('directory handle includes empty directories and respects cancellation while scanning',async()=>{
  const root=directory('project',[directory('empty'),directory('sub',[handle('a.bin','x')])]);
  const counts=[],selection=await readFolder(root,new AbortController().signal,count=>counts.push(count));
  assert.deepEqual(selection.directories,['empty','sub']);assert.equal(selection.preservesEmpty,true);
  assert.deepEqual(selection.files.map(f=>f.path),['sub/a.bin']);assert.ok(counts.length>0);
  const controller=new AbortController();controller.abort();await assert.rejects(readFolder(root,controller.signal),{name:'AbortError'});
});

test('mixed roots, traversal, duplicate files, file-parent conflicts and oversized folders are rejected before sending',()=>{
  for(const files of [[file('a/x'),file('b/y')],[file('a/../escape')],[file('a/x'),file('a/x')],[file('a/x'),file('a/x/y')]])
    assert.throws(()=>folderPayload(folderFromFiles(files)));
  const huge=file('a/b');Object.defineProperty(huge,'size',{value:512*1024*1024});
  assert.throws(()=>folderPayload(folderFromFiles([huge])),/512 MiB/);
});

test('folder upload shares progress, verifies remote completion and cancels the whole batch',async()=>{
  const selection=folderFromFiles([file('project/sub/a','bytes')]);const stages=[];let metadata,body;
  const fetcher=async(url,options)=>{
    if(options.method==='POST'){metadata=JSON.parse(options.body);return Response.json({id:'folder-upload'})}
    return Response.json({status:'done',path:'/target/project'});
  };
  const result=await uploadPayload('host','/target',selection.name,folderPayload(selection),'folder',new AbortController().signal,value=>stages.push(value),fetcher,
    async(url,blob,signal,progress)=>{body=blob;progress(blob.size)});
  assert.equal(result,'/target/project');assert.equal(metadata.kind,'folder');assert.equal(metadata.name,'project');
  assert.equal(metadata.size,body.size);assert.equal(stages.at(-1).stage,'done');
  const controller=new AbortController(),calls=[];
  await assert.rejects(uploadPayload('h','/target',selection.name,folderPayload(selection),'folder',controller.signal,()=>{},async(url,options)=>{calls.push(options.method);return Response.json({id:'cancel-folder'})},async()=>{controller.abort();throw new DOMException('cancel','AbortError')}),{name:'AbortError'});
  assert.ok(calls.includes('DELETE'));
});
