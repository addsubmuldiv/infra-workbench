import test from 'node:test';
import assert from 'node:assert/strict';
import {latestUpdate} from '../src/latestUpdate.ts';

test('continuous token updates render latest text at bounded intervals, final flush cancels pending work',()=>{
  const timers=new Map(),seen=[];let id=0;
  const buffer=latestUpdate(value=>seen.push(value),{schedule:fn=>{timers.set(++id,fn);return id},cancel:id=>timers.delete(id)});
  for(let i=0;i<100;i++)buffer.push(`text ${i}`);
  assert.equal(timers.size,1);assert.deepEqual(seen,[]);
  const [key,flush]=[...timers][0];timers.delete(key);flush();
  assert.deepEqual(seen,['text 99']);
  buffer.push('pending');buffer.push('final',true);
  assert.deepEqual(seen,['text 99','final']);assert.equal(timers.size,0);
  buffer.push('unmounted');buffer.dispose();assert.equal(timers.size,0);
});
