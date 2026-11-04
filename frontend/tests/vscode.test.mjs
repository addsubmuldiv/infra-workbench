import test from 'node:test';
import assert from 'node:assert/strict';
import {openVSCode,VSCodeError} from '../src/vscode.ts';

function fixture(states,{skip=false,signal,timeoutMs=1000}={}){
  let time=0,reads=0;const calls=[],phases=[];
  const request=async(path,method,body)=>{
    calls.push({path,method,body});
    if(path.endsWith('/prepare'))return {authority:'ssh-remote+server',tunnels:[{id:'a',name:'Proxy'}]};
    if(path==='/tunnels')return states[Math.min(reads++,states.length-1)];
    return {launched:true};
  };
  return {calls,phases,run:()=>openVSCode({request,skip,expectedAuthority:'ssh-remote+server',signal,timeoutMs,now:()=>time,wait:async()=>{time+=500},phase:p=>phases.push(p)})};
}

test('VS Code waits for every selected tunnel and then opens exactly once',async()=>{
  const f=fixture([[{id:'a',name:'Proxy',status:'connecting'}],[{id:'a',name:'Proxy',status:'connected'}]]);
  await f.run();
  assert.deepEqual(f.calls.map(c=>c.path),['/vscode/prepare','/tunnels','/tunnels','/vscode/open']);
  assert.equal(f.calls.at(-1).body.expected_authority,'ssh-remote+server');
  assert.deepEqual(f.phases,['preparing','connecting','opening']);
});

test('failed, removed or stopped prerequisite never launches automatically',async()=>{
  for(const state of [[{id:'a',name:'Proxy',status:'error',error:'port occupied'}],[],[{id:'a',name:'Proxy',status:'stopped'}]]){
    const f=fixture([state]);
    await assert.rejects(f.run(),e=>e instanceof VSCodeError&&e.canSkip);
    assert.ok(!f.calls.some(c=>c.path==='/vscode/open'));
  }
});

test('wait deadline never launches and explicit skip bypasses prepare',async()=>{
  const f=fixture([[{id:'a',name:'Proxy',status:'reconnecting'}]]);
  await assert.rejects(f.run(),e=>e.code==='TUNNEL_TIMEOUT');
  assert.ok(!f.calls.some(c=>c.path==='/vscode/open'));
  const skip=fixture([],{skip:true});await skip.run();
  assert.deepEqual(skip.calls,[{path:'/vscode/open',method:'POST',body:{skip_tunnels:true,expected_authority:'ssh-remote+server'}}]);
});

test('cancellation before or during polling never opens VS Code',async()=>{
  const controller=new AbortController();controller.abort();
  const f=fixture([],{signal:controller.signal});
  await assert.rejects(f.run(),e=>e.name==='AbortError');assert.equal(f.calls.length,0);
  const second=new AbortController();const calls=[];
  await assert.rejects(openVSCode({signal:second.signal,request:async path=>{
    calls.push(path);
    if(path.endsWith('/prepare'))return {tunnels:[{id:'a'}]};
    second.abort();return [{id:'a',status:'connected'}];
  }}),e=>e.name==='AbortError');
  assert.ok(!calls.includes('/vscode/open'));
});

test('skip preserves the prepared target and refuses to open without it',async()=>{
  const calls=[];let expected;
  const request=async(path,method,body)=>{
    calls.push({path,body});
    if(path.endsWith('/prepare'))return {authority:'ssh-remote+original',tunnels:[{id:'a'}]};
    if(path==='/tunnels')return [{id:'a',name:'Proxy',status:'error'}];
    return {launched:true};
  };
  await assert.rejects(openVSCode({request,prepared:value=>{expected=value}}),e=>e.canSkip);
  assert.equal(expected,'ssh-remote+original');
  await openVSCode({request,skip:true,expectedAuthority:expected});
  assert.deepEqual(calls.at(-1),{path:'/vscode/open',body:{skip_tunnels:true,expected_authority:'ssh-remote+original'}});
  const count=calls.length;
  await assert.rejects(openVSCode({request,skip:true}),e=>e.code==='VSCODE_TARGET_CHANGED');
  assert.equal(calls.length,count);
});
