import test from 'node:test';
import assert from 'node:assert/strict';
import {downloadOriginalLog} from '../src/logDownload.ts';

test('original download preserves raw bytes and Unicode filename, sends only location',async()=>{
  const raw=new Uint8Array([255,0,13,10,65]);
  const location={host_id:'npu',path:'/logs/精度; $(bad).log'};
  const fetcher=async(url,options)=>{
    assert.equal(url,'/api/logs/download');assert.equal(options.method,'POST');
    assert.equal(options.headers['X-IWB'],'1');assert.deepEqual(JSON.parse(options.body),location);
    return new Response(raw,{headers:{'Content-Type':'application/octet-stream','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent('NPU-精度.log')}});
  };
  const result=await downloadOriginalLog(location,fetcher);
  assert.equal(result.filename,'NPU-精度.log');
  assert.deepEqual(new Uint8Array(await result.blob.arrayBuffer()),raw);
});

test('failed downloads surface an error instead of downloading JSON as a log',async()=>{
  await assert.rejects(downloadOriginalLog({host_id:'npu',path:'/missing'},async()=>new Response(JSON.stringify({detail:'没有读取权限'}),{status:400,headers:{'Content-Type':'application/json'}})),/没有读取权限/);
});

test('aborting a download stops response buffering and preserves the abort error',async()=>{
  const controller=new AbortController();let entered;
  const started=new Promise(resolve=>{entered=resolve});
  const download=downloadOriginalLog({host_id:'server',path:'/large.bin'},async(url,options)=>{
    assert.equal(options.signal,controller.signal);
    return {ok:true,headers:new Headers(),blob:()=>new Promise((resolve,reject)=>{
      options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});entered();
    })};
  },'/api/files/download',controller.signal);
  await started;controller.abort();await assert.rejects(download,{name:'AbortError'});
});
