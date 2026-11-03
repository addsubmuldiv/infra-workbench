import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clusterGroups,selectionState} from '../src/clusterApi.ts';
const host=(id,kind)=>({id,target:id,user:null,snapshot:{fresh:true,status:'online',devices:[{kind}]}});
const hosts=[host('gpu-a','GPU'),host('npu-a','NPU'),host('gpu-other','GPU')];
const clusters=[{id:'training',name:'Training Group',revision:2,host_ids:['gpu-a','npu-a']},{id:'empty',name:'Empty',revision:1,host_ids:[]}];
test('cluster name search expands matching category members; host search includes only matching hosts',()=>{
 const group=clusterGroups(hosts,clusters,'GPU',' TRAINING ')[0];
 assert.deepEqual(group.matching.map(h=>h.id),['gpu-a']);assert.equal(group.all.length,2);
 assert.deepEqual(clusterGroups(hosts,clusters,'全部','npu-a')[0].matching.map(h=>h.id),['npu-a']);
 assert.equal(clusterGroups(hosts,clusters,'GPU','npu-a')[0].matching.length,0);
});
test('ungrouped fallback retains hosts and empty clusters remain represented',()=>{
 const groups=clusterGroups(hosts,clusters,'全部','');assert.equal(groups[1].all.length,0);
 assert.deepEqual(groups[2].all.map(h=>h.id),['gpu-other']);
 assert.deepEqual(clusterGroups(hosts,[],'全部','')[0].all,hosts);
});
test('selection partial state concerns only visible members and never selects empty groups',()=>{
 assert.deepEqual(selectionState(['gpu-a','npu-a'],new Set(['gpu-a'])),{checked:false,partial:true});
 assert.deepEqual(selectionState(['gpu-a'],new Set(['gpu-a','gpu-other'])),{checked:true,partial:false});
 assert.deepEqual(selectionState([],new Set(['gpu-a'])),{checked:false,partial:false});
});
