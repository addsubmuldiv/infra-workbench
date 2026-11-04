import {test} from 'node:test';
import assert from 'node:assert/strict';
import {idleLabel,segmentWidth,shiftDate,stepPath,heatColor,historyDeviceKind} from '../src/resourceHistoryModel.ts';
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
