import test from 'node:test';
import assert from 'node:assert/strict';
import {assistantRequest,rowTitle} from '../src/infraAssistant.ts';
import {pageFromHash} from '../src/navigation.ts';

test('assistant navigation and result titles preserve the actual target identity',()=>{
  assert.equal(pageFromHash('#assistant'),'assistant');
  assert.equal(rowTitle({type:'process',pid:123,user:'alice'}),'PID 123 · alice');
  assert.equal(rowTitle({type:'resource',kind:'NPU',device_ids:['chip:0','chip:1']}),'NPU · 2 个设备');
  assert.equal(rowTitle({type:'host',fresh:false}),'机器状态待确认');
});

test('queries are sent as JSON to the protected local backend, never URL parameters',async()=>{
  const controller=new AbortController();
  const result=await assistantRequest('/search','POST',{query:'我的 vllm 在哪里',refresh:false},controller.signal,async(url,options)=>{
    assert.equal(url,'/api/assistant/search');
    assert.equal(options.headers['X-IWB'],'1');
    assert.equal(options.cache,'no-store');
    assert.equal(options.signal,controller.signal);
    assert.equal(JSON.parse(options.body).query,'我的 vllm 在哪里');
    return new Response(JSON.stringify({items:[],coverage:{unavailable:[{alias:'离线机器'}]}}));
  });
  assert.equal(result.coverage.unavailable[0].alias,'离线机器');
});

test('missing backend and invalid model outputs remain explicit errors instead of empty matches',async()=>{
  await assert.rejects(assistantRequest('/search','POST',{},undefined,async()=>new Response(JSON.stringify({detail:'模型摘要引用了不存在的变化记录'}),{status:400})),/不存在/);
  await assert.rejects(assistantRequest('/status','GET',undefined,undefined,async()=>new Response('{}',{status:404})),/重新打开/);
});
