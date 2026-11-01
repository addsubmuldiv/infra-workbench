import test from 'node:test';
import assert from 'node:assert/strict';
import {toolPresentation} from '../src/agentChat.ts';
const tool=(status,output)=>({status,output:typeof output==='string'?output:JSON.stringify(output)});
test('partial resource queries and unavailable samples are distinct from invocation failures',()=>{
 assert.deepEqual(toolPresentation(tool('failed',{ok:false,partial:true,error:{code:'INCOMPLETE_RESOURCE_QUERY'}})),{status:'warning',label:'已返回部分结果'});
 assert.deepEqual(toolPresentation(tool('failed',{ok:false,partial:true,error:{code:'STALE_SNAPSHOT'}})),{status:'warning',label:'未取得有效采样'});
 assert.equal(toolPresentation(tool('failed',{ok:false,error:{code:'INVALID_ARGUMENT'}})).label,'调用失败');
 assert.equal(toolPresentation(tool('failed','broken JSON')).label,'调用失败');
 assert.equal(toolPresentation(tool('running',{partial:true})).status,'running');
 assert.equal(toolPresentation(tool('succeeded',{ok:true})).label,'已返回结果');
});
