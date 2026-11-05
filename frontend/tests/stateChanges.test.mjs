import test from 'node:test';
import assert from 'node:assert/strict';
import * as live from '../src/stateChanges.ts';

test('change cursor refreshes after updates and backend replacement without overlapping reads',async()=>{
  const controller=new AbortController();let reads=0,refreshes=0;
  await live.watchStateChanges({signal:controller.signal,onChange:async()=>{refreshes++},request:async(url,options)=>{
    assert.equal(options.cache,'no-store');
    const cursor=new URL(url,'http://localhost').searchParams;
    reads++;
    if(reads===2)assert.equal(cursor.get('revision'),'1');
    if(reads===4)controller.abort();
    return new Response(JSON.stringify(reads<=2?{instance:'a',revision:1}:{instance:'b',revision:0}));
  }});
  assert.equal(refreshes,2);
});

test('aborted change requests never refresh or retry',async()=>{
  const controller=new AbortController();let refreshed=false;
  await live.watchStateChanges({signal:controller.signal,onChange:()=>{refreshed=true},request:async()=>{
    controller.abort();return new Response(JSON.stringify({instance:'a',revision:1}));
  }});
  assert.equal(refreshed,false);
});

test('a failed snapshot read retries the same cursor and old backends keep ordinary polling',async()=>{
  const controller=new AbortController();const cursors=[];let reads=0;
  await live.watchStateChanges({signal:controller.signal,coalesceMs:0,retryMs:0,onChange:()=>{
    if(++reads===1)throw Error('temporary read failure');
    controller.abort();
  },request:async url=>{
    cursors.push(new URL(url,'http://localhost').searchParams.get('revision'));
    return Response.json({instance:'a',revision:5});
  }});
  assert.deepEqual(cursors,['-1','-1']);assert.equal(reads,2);
  let refreshes=0;
  await live.watchStateChanges({signal:new AbortController().signal,onChange:()=>refreshes++,request:async()=>new Response('',{status:404})});
  assert.equal(refreshes,0);
});
