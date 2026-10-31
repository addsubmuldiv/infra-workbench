import {test} from 'node:test';
import assert from 'node:assert/strict';
import {importActive,importPercent,importRequest,validateImportFile} from '../src/serverImportApi.ts';

test('import completion and background key progress are independent',()=>{
  assert.equal(importActive({status:'complete',key_total:3,key_done:1}),true);
  assert.equal(importActive({status:'complete',key_total:3,key_done:3}),false);
  assert.equal(importActive({status:'running',key_total:0,key_done:0}),true);
  assert.equal(importPercent(3,3),100);assert.equal(importPercent(0,0),0);
  assert.equal(importPercent(1,3),33);assert.equal(importPercent(7,3),100);
});

test('invalid and oversized input files fail before uploading any credentials',()=>{
  assert.doesNotThrow(()=>validateImportFile({name:'服务器.XLSX',size:100}));
  for(const file of [{name:'servers.xls',size:100},{name:'servers.xlsx',size:0},{name:'servers.xlsx',size:2*1024*1024+1}])assert.throws(()=>validateImportFile(file));
});

test('raw Excel upload sends same-origin mutation header and avoids caching',async t=>{
  const original=globalThis.fetch;t.after(()=>globalThis.fetch=original);
  const binary=new Uint8Array([80,75,3,4]);let actual;
  globalThis.fetch=async(url,options)=>{actual={url,options};return {ok:true,json:async()=>({id:'safe-token',rows:[]})}};
  await importRequest('/preview',{method:'POST',body:binary});
  assert.equal(actual.url,'/api/imports/preview');assert.equal(actual.options.body,binary);
  assert.equal(actual.options.headers.get('X-IWB'),'1');assert.equal(actual.options.cache,'no-store');
  assert.ok(!actual.url.includes('password'));
});

test('bad server responses are surfaced as errors and do not look like successful imports',async t=>{
  const original=globalThis.fetch;t.after(()=>globalThis.fetch=original);
  globalThis.fetch=async()=>({ok:false,status:400,json:async()=>({detail:'表头缺少账号'})});
  await assert.rejects(importRequest('/preview',{method:'POST'}),/表头缺少账号/);
  globalThis.fetch=async()=>({ok:false,status:404,json:async()=>({detail:'Not Found'})});
  await assert.rejects(importRequest('/latest'),/重启软件/);
});
