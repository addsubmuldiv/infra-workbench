import {i18nMock} from './i18n-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as reservations from '../src/reservations.ts';
const hosts=['a','b','c'].map(id=>({id,target:id,snapshot:{fresh:true,devices:Array.from({length:8},()=>({kind:'NPU'}))}}));
const cluster={id:'pool',name:'Pool',revision:9,host_ids:['a','b','c']};
const base={id:'rule',mode:'cluster_any',candidate_host_ids:['a','b'],cluster_id:'pool',revision:8,version:4,kind:'NPU',required_devices:4,required_hosts:2,minimum_gib:1,wait_seconds:120,email_notify:false,status:'waiting',host_states:[]};
function harness(t,{draft,items=[]}={}){
 const values=[],effects=[],cleanups=[],requests=[];let cursor=0,tree,saved=0;
 const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),useState:initial=>{const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return[values[i],v=>values[i]=typeof v==='function'?v(values[i]):v]},useEffect:fn=>effects.push(fn)};
 const api=async(path,method='GET',body)=>{requests.push({path,method,body});return path==='/clusters'?{items:[cluster]}:method==='GET'?{items}:{};};
 const source=fs.readFileSync(new URL('../src/GroupReservations.tsx',import.meta.url),'utf8')+'\nexport {GroupReservationDialog};';
 const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
 const exports={};const document={body:{},addEventListener(){},removeEventListener(){}};const window={addEventListener(){},removeEventListener(){}};
 new Function('require','exports','document','window','location',js)(name=>i18nMock(name)??(name==='react'?react:name==='react-dom'?{createPortal:node=>node}:name==='./clusterApi'?{clusterApi:api}:name==='./browserId'?{browserId:()=> 'request-id'}:name==='./reservations'?reservations:name==='./mailSettings'?{mailRequest:async()=>({reservation_available:true}),mailStatusText:{failed:'邮件发送失败',sent:'邮件已发送'}}:{}),exports,document,window,{hash:''});
 const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children??[]).flat(Infinity).flatMap(nodes)];
 const text=n=>n==null||n===false?'':typeof n!=='object'?String(n):(n.props?.children??[]).flat(Infinity).map(text).join('');
 const render=()=>{cursor=0;tree=draft?exports.GroupReservationDialog({hosts,draft,close(){},saved:async()=>saved++}):exports.GroupReservations({hosts,draft:null,onDraft(){}});return tree};
 const find=fn=>nodes(tree).find(fn);
 const field=label=>{const n=find(n=>n.type==='label'&&text(n).startsWith(label));return nodes(n).find(n=>['input','select'].includes(n.type))};
 const mount=async()=>{effects.splice(0).forEach(fn=>cleanups.push(fn()));await new Promise(resolve=>setImmediate(resolve));render()};
 t.after(()=>cleanups.forEach(fn=>fn?.()));
 return{render,mount,find,field,text,requests,saved:()=>saved,submit:()=>find(n=>n.type==='form').props.onSubmit({preventDefault(){}})};
}
test('confirmation progress uses confirmed_seconds instead of legacy idle_seconds',async t=>{
 const h=harness(t,{items:[{...base,status:'settling',confirmed_seconds:37,idle_seconds:99,remaining_seconds:83}]});h.render();await h.mount();
 const progress=h.find(n=>n.type==='progress');assert.equal(progress.props.value,37);assert.equal(progress.props.max,120);assert.ok(h.text(h.render()).includes(reservations.countdown(37)));assert.ok(!h.text(h.render()).includes(reservations.countdown(99)));
});
test('notified group shows email failure and delivery error',async t=>{
 const h=harness(t,{items:[{...base,status:'ready',email_notify:true,mail_delivery:{status:'failed',error:'SMTP authentication rejected'}}]});h.render();await h.mount();assert.match(h.text(h.render()),/邮件发送失败/);assert.match(h.text(h.render()),/SMTP authentication rejected/);
});
test('editing sends optimistic version and current cluster revision independently',async t=>{
 const h=harness(t,{draft:{editing:base}});h.render();await h.mount();await h.submit();const req=h.requests.find(r=>r.method==='PATCH');assert.equal(req.path,'/group-reservations/rule');assert.equal(req.body.version,4);assert.equal(req.body.revision,9);assert.equal(req.body.request_id,'request-id');assert.equal(h.saved(),1);
});
test('specified mode normalizes required_hosts to selected candidate count',async t=>{
 const h=harness(t,{draft:{editing:{...base,mode:'specified',candidate_host_ids:['a','b','c'],required_hosts:1}}});h.render();await h.mount();await h.submit();assert.equal(h.requests.find(r=>r.method==='PATCH').body.required_hosts,3);
});
for(const [label,value] of [['每台至少空闲设备数','0'],['每台至少空闲设备数','1.5'],['需要同时满足的机器数','3'],['需要同时满足的机器数','0'],['连续满足时间（分钟）','-1']])test(`invalid ${label}=${value} prevents saving`,async t=>{
 const h=harness(t,{draft:{editing:base}});h.render();await h.mount();h.field(label).props.onChange({target:{value}});h.render();await h.submit();h.render();assert.equal(h.requests.filter(r=>r.method==='PATCH'||r.method==='POST').length,0);assert.equal(h.saved(),0);assert.ok(h.find(n=>n.props?.role==='alert'));
});
