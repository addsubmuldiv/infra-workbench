import test from 'node:test';
import assert from 'node:assert/strict';
import {codexQuestionAnswers,codexVisibleItems,codexModelOptions} from '../src/agentChat.ts';
test('native item presentation excludes private reasoning and bounds output',()=>{
 const items=codexVisibleItems([{id:'r',type:'reasoning',data:{text:'private'}},{id:'c',type:'commandExecution',data:{command:'pwd'},output:'x'.repeat(40000)}]);
 assert.equal(items.length,1);assert.equal(items[0].id,'c');assert.equal(items[0].output.length,32000);assert.equal(items[0].output_truncated,true);
});
test('question answers bind each question and retain explicit custom answers',()=>{
 const questions=[{id:'a',question:'Choose',options:[{label:'Yes',description:''}]},{id:'b',question:'Path'}];
 assert.deepEqual(codexQuestionAnswers(questions,{a:'Yes',b:' /tmp/p '}),{a:{answers:['Yes']},b:{answers:['/tmp/p']}});
 assert.throws(()=>codexQuestionAnswers(questions,{a:'Yes',b:' '}));
});
test('model selection resets unsupported effort to the models default',()=>{
 const models=[{id:'m',defaultReasoningEffort:'medium',supportedReasoningEfforts:[{reasoningEffort:'medium'}]}];
 assert.deepEqual(codexModelOptions(models,'m','high'),{model:'m',effort:'medium'});
 assert.deepEqual(codexModelOptions([], 'missing','high'),{model:'',effort:''});
});

import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import {renderToStaticMarkup} from 'react-dom/server';
import * as helpers from '../src/agentChat.ts';
import {t as translate} from '../src/i18n.ts';
function loadHost(){
 const source=ts.transpileModule(fs.readFileSync(new URL('../src/CodexHost.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const exports={};new Function('require','exports',source)(name=>name==='react'?React:name==='react/jsx-runtime'?jsx:name==='./i18n'?{t:translate}:name==='./agentChat'?helpers:{assistantRequest:()=>Promise.reject(new Error('not used'))},exports);return exports;
}
test('native transcript renders commands and diffs without reasoning',()=>{
 const {CodexItems}=loadHost();const html=renderToStaticMarkup(React.createElement(CodexItems,{items:[{id:'r',type:'reasoning',data:{text:'PRIVATE_CHAIN'}},{id:'c',type:'commandExecution',status:'completed',data:{command:'pwd'},output:'project'},{id:'f',type:'fileChange',data:{diff:'+hello'}}]}));
 assert.match(html,/pwd/);assert.match(html,/\+hello/);assert.doesNotMatch(html,/PRIVATE_CHAIN/);
});
test('secret questions use password inputs and stale requests cannot submit',()=>{
 const {CodexQuestionForm}=loadHost();const request={id:'q',run_id:'old',status:'pending',questions:[{id:'secret',question:'Token',isSecret:true}]};
 const html=renderToStaticMarkup(React.createElement(CodexQuestionForm,{request,chatId:'chat',activeRun:'new',onUpdate:()=>{}}));
 assert.match(html,/type="password"/);assert.match(html,/disabled/);assert.doesNotMatch(html,/<button/);
});


test('Codex host exposes execution and planning modes independently from permissions',()=>{
 const {CodexHost}=loadHost();const value={cwd:'',model:'',effort:'',multi_agent:false,enabled_mcp_servers:[],enabled_plugins:[],collaboration_mode:'plan'};
 const html=renderToStaticMarkup(React.createElement(CodexHost,{value,onChange:()=>{},disabled:true}));
 assert.match(html,/value="plan" selected/);assert.match(html,/value="default"/);assert.match(html,/规划模式不改变执行权限/);
});

test('output pages append only at the expected offset and stay bounded',()=>{
 const initial={text:'first',next_offset:5,total:9,truncated:false};
 const page={text:'next',next_offset:null,total:9,truncated:false};
 const result=helpers.appendCodexOutputPage(initial,5,page);
 assert.equal(result.text,'firstnext');assert.equal(result.next_offset,null);
 assert.throws(()=>helpers.appendCodexOutputPage(result,5,page));
 assert.throws(()=>helpers.appendCodexOutputPage(initial,0,page));
 const bounded=helpers.appendCodexOutputPage(initial,5,{text:'x'.repeat(1048576),next_offset:null,total:1048581,truncated:true});
 assert.equal(bounded.text.length,1048576);assert.equal(bounded.truncated,true);assert.equal(bounded.next_offset,null);
});

test('preview paging is offered independently of retention truncation',()=>{
 const {CodexItems}=loadHost();const html=renderToStaticMarkup(React.createElement(CodexItems,{chatId:'chat',runId:'run',items:[{id:'c',type:'commandExecution',data:{},output:'preview',output_total:40000,output_next_offset:32000,output_truncated:false}]}));
 assert.match(html,/读取后续输出/);assert.doesNotMatch(html,/保留上限/);
});

test('preview preserves Unicode code point offsets used by server paging',()=>{
 const output='😀'.repeat(32000);const [item]=helpers.codexVisibleItems([{id:'u',type:'commandExecution',data:{},output,output_next_offset:32000}]);
 assert.equal(item.output,output);assert.equal(item.output_truncated,false);
});
