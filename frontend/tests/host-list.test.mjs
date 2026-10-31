import {test} from 'node:test';
import assert from 'node:assert/strict';
import {HOST_CATEGORIES,filterHosts} from '../src/hostList.ts';

const host=(target,kinds,fresh=true)=>({id:target,target,snapshot:{fresh,devices:kinds.map(kind=>({kind}))}});
const hosts=[host('H200-CX',['GPU']),host('A3-new',['NPU','NPU']),host('mixed',['GPU','NPU']),host('waiting',[]),host('offline-npu',['NPU'],false)];

test('all machines remain discoverable, including machines awaiting their first sample',()=>{
  assert.deepEqual(HOST_CATEGORIES,['全部','GPU','NPU']);
  assert.deepEqual(filterHosts(hosts,'全部').map(h=>h.id),hosts.map(h=>h.id));
});

test('GPU and NPU categories use device types and retain last-known offline types',()=>{
  assert.deepEqual(filterHosts(hosts,'GPU').map(h=>h.id),['H200-CX','mixed']);
  assert.deepEqual(filterHosts(hosts,'NPU').map(h=>h.id),['A3-new','mixed','offline-npu']);
});

test('search and category filters work together while preserving host objects',()=>{
  assert.deepEqual(filterHosts(hosts,'GPU','  h200 ').map(h=>h.id),['H200-CX']);
  assert.deepEqual(filterHosts(hosts,'GPU','A3'),[]);
  assert.equal(filterHosts(hosts,'NPU','A3')[0],hosts[1]);
  assert.equal(hosts.length,5);
});
