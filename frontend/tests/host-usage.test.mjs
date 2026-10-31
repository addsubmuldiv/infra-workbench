import {test} from 'node:test';
import assert from 'node:assert/strict';
import {deviceUsage} from '../src/hostUsage.ts';

const device=(overrides={})=>({id:'0',kind:'NPU',card_id:'0',processes:[],processes_known:true,health:'OK',...overrides});

test('counts individual devices, including two dies on the same physical card',()=>{
  const devices=[device({id:'0',chip_id:'0',processes:[{pid:123}]}),device({id:'1',chip_id:'1'})];
  assert.deepEqual(deviceUsage({fresh:true,devices}),{total:2,occupied:1,idle:1,unknown:0,abnormal:0});
});

test('unknown processes and alarms are not counted as idle; warnings remain usable',()=>{
  const devices=[device({health:'Warning'}),device({processes_known:false}),device({health:'Alarm'}),device({processes_known:false,processes:[{pid:123}]})];
  assert.deepEqual(deviceUsage({fresh:true,devices}),{total:4,occupied:1,idle:1,unknown:1,abnormal:1});
});

test('expired samples cannot claim current occupancy or availability',()=>{
  const devices=[device(),device({processes:[{pid:123}]})];
  assert.deepEqual(deviceUsage({fresh:false,devices}),{total:2,occupied:0,idle:0,unknown:2,abnormal:0});
  assert.deepEqual(deviceUsage({fresh:false,devices:[]}),{total:0,occupied:0,idle:0,unknown:0,abnormal:0});
});
