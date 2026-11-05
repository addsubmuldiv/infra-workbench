import {test} from 'node:test';
import assert from 'node:assert/strict';
import {idleLabel,segmentWidth,shiftDate,stepPath,heatColor,historyDeviceKind,mergeHistoryDisplaySegments} from '../src/resourceHistoryModel.ts';
test('unknown inventory and incomplete data are never labelled exact zero',()=>{
 assert.equal(idleLabel({idle_count:0,unknown_count:null,inventory_known:false,complete:false},true),'Unknown inventory');
 assert.equal(idleLabel({idle_count:3,unknown_count:2,inventory_known:true,complete:false},true),'≥3, 2 unknown');
 assert.equal(idleLabel({idle_count:0,unknown_count:0,inventory_known:true,complete:true},true),'0');
});
test('date navigation crosses month and leap year boundaries',()=>{assert.equal(shiftDate('2024-03-01',-1),'2024-02-29');assert.equal(shiftDate('2026-12-31',1),'2027-01-01')});
test('interval widths use actual day length and clip to query boundaries',()=>{assert.equal(segmentWidth(0,3600,0,23*3600),100/23);assert.equal(segmentWidth(-100,100,0,200),50)});
test('plot leaves unknown inventory and future intervals unpainted',()=>{
 const base={start:0,end:10,idle_count:3,unknown_count:2,inventory_known:true,reason:null};
 assert.ok(stepPath([base],0,10,8).includes('V120'));
 assert.equal(stepPath([{...base,inventory_known:false},{...base,reason:'future'}],0,10,8),'');
 assert.notEqual(heatColor(0,8),heatColor(8,8));
});

const kindHosts=[{id:'n',snapshot:{devices:[{kind:'NPU'}]}},{id:'g',snapshot:{devices:[{kind:'GPU'}]}},{id:'pending',snapshot:{devices:[]}}];
test('history follows selected hardware after host selection or delayed inventory',()=>{
 assert.equal(historyDeviceKind(kindHosts,['n'],'GPU'),'NPU');
 assert.equal(historyDeviceKind(kindHosts,['g'],'NPU'),'GPU');
 assert.equal(historyDeviceKind(kindHosts,['n','pending'],'GPU'),'NPU');
 assert.equal(historyDeviceKind(kindHosts,['pending'],'NPU'),'NPU');
 assert.equal(historyDeviceKind(kindHosts,[],'GPU'),'GPU');
});
test('mixed history scopes retain manual GPU or NPU selection',()=>{
 assert.equal(historyDeviceKind(kindHosts,['n','g'],'NPU'),'NPU');
 assert.equal(historyDeviceKind(kindHosts,['n','g'],'GPU'),'GPU');
});

const idle=(start,end,n=8,extra={})=>({start,end,idle_count:n,busy_count:8-n,unknown_count:0,total_count:8,inventory_known:true,complete:true,machine_state:n===8?'whole_idle':'partial_idle',reason:'',devices:[],run_id:'run',...extra});
const gap=(start,end,reason='sampling_gap')=>({...idle(start,end,0),inventory_known:false,complete:false,total_count:null,unknown_count:null,machine_state:'unknown',reason});
test('display merges repeated counts and a short reconnect without mutating source evidence',()=>{
 const raw=[idle(0,10),idle(10,20),gap(20,30),idle(30,50)];const before=JSON.stringify(raw);
 const result=mergeHistoryDisplaySegments(raw);
 assert.equal(result.length,1);assert.equal(result[0].end,50);assert.equal(result[0].bridged_unknown_seconds,10);
 assert.equal(JSON.stringify(raw),before);
});
test('display does not bridge long gaps, different counts, restart, unknown edges or identity changes',()=>{
 for(const raw of [[idle(0,10),gap(10,200),idle(200,220)],[idle(0,10),gap(10,20),idle(20,30,4)],[idle(0,10),gap(10,20,'backend_stopped'),idle(20,30)],[idle(0,10),gap(10,20),idle(20,30,8,{run_id:'new'})],[gap(0,10),idle(10,20)],[idle(0,10),gap(10,20)]])assert.ok(mergeHistoryDisplaySegments(raw).length>1);
 const a=idle(0,10,8,{devices:[{identity:['old']}]});const b=idle(20,30,8,{devices:[{identity:['new']}]});assert.equal(mergeHistoryDisplaySegments([a,gap(10,20),b]).length,3);
 assert.equal(mergeHistoryDisplaySegments([idle(0,10),gap(10,20),idle(20,30)],0).length,3);
});

test('unknown hatching covers only unknown devices above the confirmed idle count',()=>{
 assert.equal(stepPath([idle(0,10,3)],0,10,8,'unknown_count'),'');
 assert.equal(stepPath([idle(0,10,3,{unknown_count:2,complete:false})],0,10,8,'unknown_count'),'M0,120V80H1000V120Z');
});
