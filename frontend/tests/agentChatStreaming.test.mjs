import test from 'node:test';
import assert from 'node:assert/strict';
import * as chatAPI from '../src/agentChat.ts';
const base={id:'a'.repeat(32),title:'对话',created:1,updated:2,active_run:'run1',turns:[{id:'u1',role:'user',content:'问',created:1},{id:'t1',role:'assistant',content:'',created:2,status:'running'}]};
const event=(content,updated=3,active_run='run1')=>({type:'turn',data:{chat_id:base.id,title:'问题',updated,active_run,turn:{id:'t1',role:'assistant',content,created:2,status:active_run?'running':'completed'}}});
const frame=(type,data)=>`event: ${type}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`;

test('fragmented UTF8 and CRLF SSE delivers text before stream completion',async()=>{
  assert.equal(typeof chatAPI.watchChat,'function');
  let source;const received=[];const abort=new AbortController();
  const body=new ReadableStream({start(controller){source=controller}});
  const done=chatAPI.watchChat(base.id,{signal:abort.signal,onEvent:value=>received.push(value),request:async(url,options)=>{assert.equal(url,`/api/assistant/chats/${base.id}/events`);assert.equal(options.headers['X-IWB'],'1');return new Response(body,{headers:{'Content-Type':'text/event-stream'}})}});
  const bytes=new TextEncoder().encode(': heartbeat\r\n\r\n'+frame('snapshot',base)+frame('turn',event('你好 🌍').data));
  for(const byte of bytes)source.enqueue(Uint8Array.of(byte));
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(received.length,2);assert.equal(received[1].data.turn.content,'你好 🌍');
  abort.abort();await done;assert.equal(received.length,2);
});

test('reconnect reads a fresh snapshot after truncated JSON and premature EOF',async()=>{
  assert.equal(typeof chatAPI.watchChat,'function');
  const received=[];let calls=0;const abort=new AbortController();
  await chatAPI.watchChat(base.id,{signal:abort.signal,retryMs:1,onEvent:value=>{received.push(value);if(received.length===2)abort.abort()},request:async()=>{calls++;return new Response(calls===1?frame('snapshot',base)+'event: turn\ndata: {"chat_id":':frame('snapshot',{...base,updated:4,active_run:null}),{headers:{'Content-Type':'text/event-stream'}})}});
  assert.equal(calls,2);assert.deepEqual(received.map(value=>value.data.updated),[2,4]);
});

test('abort prevents stale response delivery even when fetch ignores cancellation',async()=>{
  assert.equal(typeof chatAPI.watchChat,'function');
  let release;const response=new Promise(resolve=>release=resolve);const received=[];const abort=new AbortController();
  const done=chatAPI.watchChat(base.id,{signal:abort.signal,onEvent:value=>received.push(value),request:()=>response});
  abort.abort();release(new Response(frame('snapshot',base),{headers:{'Content-Type':'text/event-stream'}}));await done;assert.deepEqual(received,[]);
});

test('malformed complete event reports an error and reconnects without publishing invalid data',async()=>{
  assert.equal(typeof chatAPI.watchChat,'function');
  const abort=new AbortController();const errors=[];const received=[];let calls=0;
  await chatAPI.watchChat(base.id,{signal:abort.signal,retryMs:1,onError:error=>errors.push(error),onEvent:value=>{received.push(value);abort.abort()},request:async()=>new Response(++calls===1?'event: turn\ndata: {bad}\n\n':frame('snapshot',base),{headers:{'Content-Type':'text/event-stream'}})});
  assert.equal(errors.length,1);assert.equal(received.length,1);assert.equal(calls,2);
});

test('turn replacement preserves history and rejects stale chat, run and timestamp updates',()=>{
  assert.equal(typeof chatAPI.applyChatEvent,'function');
  const first=chatAPI.applyChatEvent(base,event('你'));assert.equal(first.turns.length,2);assert.equal(first.turns[1].content,'你');
  const final=chatAPI.applyChatEvent(first,event('你好',4,null));assert.equal(final.active_run,null);assert.equal(final.turns[1].content,'你好');
  for(const stale of [event('旧',1),{...event('旧'),data:{...event('旧').data,chat_id:'b'.repeat(32)}},event('旧',5,'other-run')])assert.equal(chatAPI.applyChatEvent(first,stale),first);
  const next={...base,updated:6,active_run:'run2',turns:[...base.turns,{id:'t2',role:'assistant',content:'新',created:6,status:'running'}]};
  assert.equal(chatAPI.applyChatEvent(next,event('旧结尾',7,null)),next);
});

test('scroll following changes only the transcript when its reader is near bottom',()=>{
  assert.equal(typeof chatAPI.shouldFollowChat,'function');
  assert.equal(chatAPI.shouldFollowChat({scrollHeight:1000,clientHeight:400,scrollTop:580}),true);
  assert.equal(chatAPI.shouldFollowChat({scrollHeight:1000,clientHeight:400,scrollTop:200}),false);
});


test('idle snapshot and final turn close the subscription without idle polling',async()=>{
  for(const [type,data] of [['snapshot',{...base,active_run:null}],['turn',event('完成',4,null).data]]){
    let calls=0;const received=[];
    await chatAPI.watchChat(base.id,{signal:new AbortController().signal,retryMs:1,onEvent:value=>received.push(value),request:async()=>{calls++;if(calls>1)throw new Error('unexpected reconnect');return new Response(frame(type,data),{headers:{'Content-Type':'text/event-stream'}})}});
    assert.equal(calls,1);assert.equal(received.length,1);
  }
});

test('network failures recover through a snapshot and abort interrupts a blocked read',async()=>{
  const abort=new AbortController();const errors=[];const received=[];let calls=0;
  const done=chatAPI.watchChat(base.id,{signal:abort.signal,retryMs:1,onError:error=>errors.push(error),onEvent:value=>{received.push(value);abort.abort()},request:async()=>{if(++calls===1)throw new Error('offline');return new Response(frame('snapshot',base),{headers:{'Content-Type':'text/event-stream'}})}});
  await done;assert.equal(errors.length,1);assert.equal(received.length,1);
  const blockedAbort=new AbortController();let cancelled=false;
  const blocked=chatAPI.watchChat(base.id,{signal:blockedAbort.signal,onEvent:()=>assert.fail('no events'),request:async()=>new Response(new ReadableStream({cancel(){cancelled=true}}),{headers:{'Content-Type':'text/event-stream'}})});
  await new Promise(resolve=>setTimeout(resolve,5));blockedAbort.abort();await blocked;assert.equal(cancelled,true);
});

test('an older snapshot cannot overwrite current text and a fresh snapshot restores complete history',()=>{
  const current=chatAPI.applyChatEvent(base,event('已经收到',5));
  assert.equal(chatAPI.applyChatEvent(current,{type:'snapshot',data:base}),current);
  const fresh={...base,updated:6,turns:[...base.turns,{id:'u2',role:'user',content:'追问',created:6}]};
  assert.equal(chatAPI.applyChatEvent(current,{type:'snapshot',data:fresh}),fresh);
});

test('CR-only SSE terminator at EOF publishes the complete final frame',async()=>{
  const received=[];const abort=new AbortController();let calls=0;
  await chatAPI.watchChat(base.id,{signal:abort.signal,retryMs:1,onEvent:value=>received.push(value),request:async()=>{if(++calls>1){abort.abort();throw new Error('unexpected reconnect')}return new Response(`event: snapshot\rdata: ${JSON.stringify({...base,active_run:null})}\r\r`,{headers:{'Content-Type':'text/event-stream'}})}});
  assert.equal(received.length,1);assert.equal(calls,1);
});

test('events 404 preserves an existing active chat and reports the required backend upgrade once',async()=>{
  const calls=[],errors=[],received=[];let state=base;
  await chatAPI.watchChat(base.id,{signal:new AbortController().signal,retryMs:1,onError:error=>errors.push(error.message),onEvent:value=>{received.push(value);state=chatAPI.applyChatEvent(state,value)},request:async(url,options)=>{
    calls.push(url);assert.equal(options.headers['X-IWB'],'1');
    return url.endsWith('/events')?new Response('',{status:404}):Response.json({...base,updated:3});
  }});
  assert.deepEqual(calls,[`/api/assistant/chats/${base.id}/events`,`/api/assistant/chats/${base.id}`]);
  assert.equal(state.id,base.id);assert.equal(state.active_run,'run1');assert.equal(received[0].type,'snapshot');assert.equal(errors.length,1);assert.match(errors[0],/新版后台/);
});

test('events 404 restores an existing completed chat snapshot without an upgrade error',async()=>{
  const received=[],errors=[];
  await chatAPI.watchChat(base.id,{signal:new AbortController().signal,onEvent:value=>received.push(value),onError:error=>errors.push(error),request:async url=>url.endsWith('/events')?new Response('',{status:404}):Response.json({...base,updated:4,active_run:null})});
  assert.equal(received.length,1);assert.equal(received[0].type,'snapshot');assert.equal(received[0].data.active_run,null);assert.deepEqual(errors,[]);
});

test('events 404 means deleted only after the ordinary chat endpoint also returns 404',async()=>{
  const received=[],calls=[];
  await chatAPI.watchChat(base.id,{signal:new AbortController().signal,onEvent:value=>received.push(value),request:async url=>{calls.push(url);return new Response('',{status:404})}});
  assert.equal(calls.length,2);assert.deepEqual(received,[{type:'deleted',data:{chat_id:base.id}}]);
});
