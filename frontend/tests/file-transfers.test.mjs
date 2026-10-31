import test from 'node:test';
import assert from 'node:assert/strict';
import {sendUpload,uploadFile} from '../src/fileTransfers.ts';
import {downloadOriginalLog} from '../src/logDownload.ts';
import {searchFiles} from '../src/files.ts';

test('upload tracks local and remote stages and does not succeed until server verification',async()=>{
  const stages=[],requests=[];let checks=0;
  const file=new File([new Uint8Array([0,255,10])],'example.bin');
  const fetcher=async(url,options)=>{
    requests.push({url,options});
    if(options.method==='POST')return Response.json({id:'test-upload'});
    checks++;return Response.json(checks===1?{status:'sending',sent:2,total:3}:{status:'done',sent:3,total:3,path:'/target/example.bin'});
  };
  const path=await uploadFile('host','/target',file,new AbortController().signal,value=>stages.push(value),fetcher,
    async(url,actual,signal,progress)=>{assert.equal(url,'/api/files/uploads/test-upload');assert.equal(actual,file);progress(3)});
  assert.equal(path,'/target/example.bin');
  assert.deepEqual(JSON.parse(requests[0].options.body),{host_id:'host',path:'/target',name:'example.bin',size:3});
  assert.equal(requests[0].options.headers['X-IWB'],'1');
  assert.ok(stages.some(value=>value.stage==='sending'&&value.loaded===2));
  assert.equal(stages.at(-1).stage,'done');
});
test('cancelling an upload requests remote cancellation and never reports success',async()=>{
  const controller=new AbortController(),methods=[],stages=[];
  await assert.rejects(uploadFile('host','/target',new File(['x'],'x.txt'),controller.signal,value=>stages.push(value),
    async(url,options)=>{methods.push(options.method||'GET');return Response.json({id:'cancel-upload'})},
    async()=>{controller.abort();throw new DOMException('cancelled','AbortError')}),{name:'AbortError'});
  assert.ok(methods.includes('DELETE'));assert.ok(!stages.some(value=>value.stage==='done'));
});
test('XHR sends binary bodies and maps a real browser abort to AbortError',async()=>{
  const controller=new AbortController();let request;
  const pending=sendUpload('/api/files/uploads/id',new Blob(['bytes']),controller.signal,()=>{},()=>request={
    upload:{},open(method,url){assert.equal(method,'PUT');assert.equal(url,'/api/files/uploads/id')},
    setRequestHeader(){},send(body){assert.equal(body.size,5)},abort(){this.onabort()}});
  controller.abort();await assert.rejects(pending,{name:'AbortError'});
});
test('downloads report byte progress while preserving original binary data',async()=>{
  const raw=new Uint8Array([0,255,13,10]),seen=[];
  const result=await downloadOriginalLog({host_id:'host',path:'/tmp/raw'},async()=>new Response(raw,{headers:{'Content-Length':'4'}}),
    '/api/files/download',undefined,(loaded,total)=>seen.push({loaded,total}));
  assert.deepEqual(new Uint8Array(await result.blob.arrayBuffer()),raw);
  assert.deepEqual(seen[0],{loaded:0,total:4});assert.deepEqual(seen.at(-1),{loaded:4,total:4});
});
test('search defaults to indexed-first and explicit real-time search bypasses it',async()=>{
  let body;
  const fetcher=async(url,options)=>{assert.equal(url,'/api/files/search');body=JSON.parse(options.body);return Response.json({entries:[],engine:'find'})};
  await searchFiles('host','/data','Model',true,false,fetcher);assert.equal(body.realtime,false);
  await searchFiles('host','/data','Model',true,true,fetcher);assert.equal(body.realtime,true);assert.equal(body.recursive,true);
});
