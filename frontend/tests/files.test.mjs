import test from 'node:test';
import assert from 'node:assert/strict';
import {listDirectory} from '../src/files.ts';
import {downloadOriginalLog} from '../src/logDownload.ts';

test('directory request preserves literal paths and pagination',async()=>{
  const path='/data/中文; $(no-exec)';
  const data={path,parent:'/data',entries:[],total:0,next_offset:null};
  const result=await listDirectory('server',path,500,async(url,options)=>{
    assert.equal(url,'/api/files/browse');assert.equal(options.headers['X-IWB'],'1');
    assert.deepEqual(JSON.parse(options.body),{host_id:'server',path,offset:500});
    return new Response(JSON.stringify(data));
  });
  assert.deepEqual(result,data);
});
test('permission failures are shown as errors rather than empty directories',async()=>{
  await assert.rejects(listDirectory('server','/root',0,async()=>new Response(JSON.stringify({detail:'没有权限'}),{status:400})),/没有权限/);
});
test('file browser downloads original binary through the files endpoint',async()=>{
  const raw=new Uint8Array([0,255,13,10]);
  const file=await downloadOriginalLog({host_id:'server',path:'/tmp/check.bin'},async(url)=>{
    assert.equal(url,'/api/files/download');return new Response(raw);
  },'/api/files/download');
  assert.equal(file.filename,'check.bin');assert.deepEqual(new Uint8Array(await file.blob.arrayBuffer()),raw);
});
