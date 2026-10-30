import test from 'node:test';
import assert from 'node:assert/strict';
import {singleFlight} from '../src/requests.ts';

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
