import {test} from 'node:test';
import assert from 'node:assert/strict';
import {filterHosts} from '../src/hostList.ts';
import {clusterGroups} from '../src/clusterApi.ts';

test('machine and cluster filters accept aliases without losing IP or category filtering',()=>{
 const hosts=[{id:'a',target:'10.0.0.1',alias:'训练机 A3',user:null,snapshot:{fresh:true,status:'online',devices:[{kind:'GPU'}]}}];
 assert.equal(filterHosts(hosts,'GPU','训练机 a3').length,1);
 assert.equal(filterHosts(hosts,'GPU','10.0.0.1').length,1);
 assert.equal(filterHosts(hosts,'NPU','训练机').length,0);
 assert.equal(clusterGroups(hosts,[],'GPU','训练机')[0].matching.length,1);
 assert.equal(clusterGroups(hosts,[],'NPU','训练机')[0].matching.length,0);
 assert.equal(clusterGroups(hosts,[],'GPU','10.0.0.1')[0].matching.length,1);
});
