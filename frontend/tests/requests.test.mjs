import test from 'node:test';
import assert from 'node:assert/strict';
import {singleFlight,reuseStateSnapshot} from '../src/requests.ts';

test('unchanged polls reuse the entire state, while changes preserve unaffected machines',()=>{
  const before={server_time:10,hosts:[{id:'a',snapshot:{fresh:true,devices:[{id:'0',utilization:10}]}},{id:'b',snapshot:{fresh:true,devices:[]}}],events:[],reservations:[]};
  const next=structuredClone(before);next.server_time=12;
  assert.equal(reuseStateSnapshot(before,next),before);
  next.hosts[0].snapshot.devices[0].utilization=20;
  const updated=reuseStateSnapshot(before,next);
  assert.notEqual(updated,before);assert.equal(updated.server_time,12);
  assert.notEqual(updated.hosts[0],before.hosts[0]);assert.equal(updated.hosts[1],before.hosts[1]);
  assert.equal(updated.events,before.events);assert.equal(before.hosts[0].snapshot.devices[0].utilization,10);
});

test('freshness, removed fields, notifications and initial readiness still update',()=>{
  const before={server_time:0,hosts:[{id:'a',snapshot:{fresh:true,error:'old'}}],events:[]};
  const ready=reuseStateSnapshot(before,{...before,server_time:10});assert.notEqual(ready,before);
  const changed=reuseStateSnapshot(ready,{server_time:12,hosts:[{id:'a',snapshot:{fresh:false}}],events:[{id:1,message:'ready'}]});
  assert.equal(changed.hosts[0].snapshot.fresh,false);assert.equal('error' in changed.hosts[0].snapshot,false);assert.equal(changed.events.length,1);
});

test('slow state reads are shared rather than piling up or returning out of order',async()=>{
  let calls=0,finish;
  const read=singleFlight(()=>{calls++;return new Promise(resolve=>{finish=resolve})});
  const requests=Array.from({length:20},()=>read());
  await Promise.resolve();assert.equal(calls,1);
  finish('snapshot');assert.deepEqual(await Promise.all(requests),Array(20).fill('snapshot'));
  const next=read();await Promise.resolve();assert.equal(calls,2);finish('new');assert.equal(await next,'new');
});

test('a failed state read releases the slot so polling can recover',async()=>{
  let calls=0;
  const read=singleFlight(()=>{if(++calls===1)throw new Error('offline');return Promise.resolve('recovered')});
  await assert.rejects(read(),/offline/);assert.equal(await read(),'recovered');
});
