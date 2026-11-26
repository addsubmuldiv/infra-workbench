import test from 'node:test';
import assert from 'node:assert/strict';
import {createDemoRuntime,installDemoNetwork} from '../../src/features/onboarding/demoRuntime.ts';

test('demo owns state and workspace without contacting backend',async()=>{
 const demo=createDemoRuntime();
 const state=await (await demo.fetch('/api/state')).json();
 assert.equal(state.hosts.length,8);assert.equal(state.hosts.filter(h=>h.snapshot.fresh).length,6);
 assert.ok(state.hosts.some(h=>h.snapshot.status==='stale'&&h.snapshot.devices.length));
 await demo.fetch('/api/workspace-state',{method:'PUT',body:JSON.stringify({values:{theme:'demo'}})});
 assert.equal((await (await demo.fetch('/api/workspace-state')).json()).values.theme,'demo');
 assert.equal((await (await createDemoRuntime().fetch('/api/workspace-state')).json()).values.theme,undefined);
 assert.equal((await demo.fetch('/api/hosts/real-host',{method:'DELETE'})).status,403);
 assert.equal((await demo.fetch('/api/settings/agent',{method:'PUT',body:'{}'})).status,403);
 assert.equal((await demo.fetch('https://example.com/api/state')).status,403);
 assert.equal((await demo.fetch(new Request('https://example.com/api/state'))).status,403);
});
test('training completion changes only fake devices and alerts exactly once',async()=>{
 const demo=createDemoRuntime();demo.finishTraining();demo.finishTraining();
 const state=await (await demo.fetch('/api/state')).json();
 assert.equal(state.hosts.find(h=>h.id==='demo-gpu-busy').snapshot.devices[0].processes.length,0);
 assert.equal(state.reservations[0].status,'ready');assert.equal(state.group_reservations[0].status,'ready');
 assert.equal(state.events.filter(e=>e.url.startsWith('#reservations?group=')).length,1);
 assert.equal(state.events.filter(e=>e.url.startsWith('#overview?host=')).length,1);
 demo.reset();assert.equal((await (await demo.fetch('/api/state')).json()).events.length,0);
});
test('reservations are created updated and deleted in memory',async()=>{
 const demo=createDemoRuntime();const body={host_id:'demo-gpu-busy',mode:'fixed',devices:['0'],minimum_gib:1,wait_seconds:0};
 const created=await (await demo.fetch('/api/reservations',{method:'POST',body:JSON.stringify(body)})).json();
 assert.equal(created.status,'waiting');
 assert.equal((await demo.fetch('/api/reservations/'+created.id,{method:'PATCH',body:JSON.stringify({...body,devices:['1']})})).status,200);
 assert.equal((await demo.fetch('/api/reservations/'+created.id,{method:'DELETE'})).status,200);
 assert.equal((await demo.fetch('/api/reservations',{method:'POST',body:JSON.stringify({...body,host_id:'real'})})).status,403);
});
test('network guard blocks alternate transports and never falls back',async()=>{
 let calls=0;const surface={fetch:()=>{calls++;},WebSocket:class{},EventSource:class{},XMLHttpRequest:class{},navigator:{sendBeacon:()=>{calls++;}}};
 installDemoNetwork(surface,createDemoRuntime());
 assert.equal((await surface.fetch('/mcp',{method:'POST'})).status,403);
 assert.throws(()=>new surface.WebSocket('ws://localhost/api/terminal/x'),/Demo/);
 assert.throws(()=>new surface.EventSource('/api/events'),/Demo/);
 assert.throws(()=>new surface.XMLHttpRequest(),/Demo/);
 assert.equal(surface.navigator.sendBeacon('/api/x','secret'),false);assert.equal(calls,0);
});

test('desktop demo lets Tauri report ready without forwarding application traffic',async()=>{
 for(const origin of ['http://ipc.localhost','ipc://localhost']){
  const calls=[];
  const surface={
   fetch:async(input)=>{calls.push(input);return new Response('null',{headers:{'Tauri-Response':'ok'}})},
   __TAURI_INTERNALS__:{convertFileSrc:(command,protocol)=>{assert.equal(protocol,'ipc');return `${origin}/${command}`}},
  };
  installDemoNetwork(surface,createDemoRuntime());
  const init={method:'POST',headers:{'Tauri-Invoke-Key':'test','Tauri-Callback':'1','Tauri-Error':'2'}};
  for(const command of ['desktop_ready','main_window_action']){
   assert.equal((await surface.fetch(`${origin}/${command}`,init)).headers.get('Tauri-Response'),'ok');
  }
  assert.equal((await surface.fetch(`${origin}/desktop_update_install`,init)).status,403);
  assert.equal((await surface.fetch('http://127.0.0.1:8765/api/state',init)).status,403);
  assert.equal((await surface.fetch(`${origin}/desktop_ready`,{method:'POST'})).status,403);
  assert.equal(calls.length,2);
 }
});

test('resource history preserves collection gaps and supports a selected cluster',async()=>{
 const demo=createDemoRuntime();
 const clusters=await (await demo.fetch('/api/clusters')).json();
 const gpu=clusters.items.find(c=>c.id==='demo-gpu');
 const result=await (await demo.fetch('/api/resource-history?'+new URLSearchParams({
  host_ids:gpu.host_ids.join(','),date:'2026-11-26',timezone:'Asia/Hong_Kong',kind:'GPU',start_time:'09:00',end_time:'10:00',
 }))).json();
 assert.equal(result.end-result.start,3600);
 assert.equal(result.hosts.length,3);
 assert.ok(result.sample_count>0);
 assert.ok(result.segments.some(segment=>segment.unknown===3));
 assert.ok(result.summary.idle_device_hours>0);
});

test('precision demo aligns actual steps and allows inspecting a source row',async()=>{
 const demo=createDemoRuntime();
 const request=async(path,body)=>(await demo.fetch('/api/logs'+path,{method:'POST',body:JSON.stringify(body)})).json();
 const samples=await request('/demo',{});
 const result=await request('/compare',{baseline:samples.baseline.id,candidate:samples.candidate.id,metrics:['loss']});
 assert.deepEqual(result.alignment,{common_steps:23,baseline_only:1,candidate_only:1});
 assert.equal(result.metrics[0].points.some(point=>point.step===7),false);
 const point=result.metrics[0].points.at(-1);
 const row=await (await demo.fetch('/api/logs/'+samples.candidate.id+'/record?group=rank0&line='+point.candidate_line)).json();
 assert.equal(row.step,point.step);
});

test('port forwarding changes demo rules without creating network URLs',async()=>{
 const demo=createDemoRuntime();
 const base='/api/hosts/demo-gpu-busy';
 const tunnel=await (await demo.fetch(base+'/tunnels/demo-editor/start',{method:'POST'})).json();
 assert.equal(tunnel.status,'connected');
 const service=await (await demo.fetch(base+'/services/demo-tensorboard/start',{method:'POST'})).json();
 assert.equal(service.status,'active');
 assert.equal(service.url,null);
 assert.equal((await demo.fetch(base+'/tunnels/unknown/start',{method:'POST'})).status,403);
 demo.reset();
 const reset=await (await demo.fetch(base+'/services')).json();
 assert.equal(reset[0].status,'stopped');
});

test('preflight distinguishes a free demo device from an occupied one',async()=>{
 const demo=createDemoRuntime();
 const check=async host_id=>(await demo.fetch('/api/preflight',{method:'POST',body:JSON.stringify({host_id,devices:['0'],minimum_gib:24})})).json();
 assert.equal((await check('demo-gpu-free')).status,'PASS');
 assert.equal((await check('demo-gpu-busy')).status,'FAIL');
});

test('file save checks revision and reset restores all sample contents',async()=>{
 const demo=createDemoRuntime();const path='/demo/README.md';const command={host_id:'demo-gpu-free',path,op:'read'};
 const before=await (await demo.fetch('/api/files/operation',{method:'POST',body:JSON.stringify(command)})).json();
 assert.equal((await demo.fetch('/api/files/operation',{method:'POST',body:JSON.stringify({...command,op:'save',revision:'stale',content:'edited'})})).status,409);
 await demo.fetch('/api/workspace-state',{method:'PUT',body:JSON.stringify({values:{selection:'changed'}})});
 assert.equal((await demo.fetch('/api/files/operation',{method:'POST',body:JSON.stringify({...command,op:'save',revision:before.revision,content:'edited'})})).status,200);
 demo.reset();const after=await (await demo.fetch('/api/files/operation',{method:'POST',body:JSON.stringify(command)})).json();assert.equal(after.content,before.content);
});

test('demo host reads work without newer structuredClone API and do not expose mutable state',async()=>{
 const previous=globalThis.structuredClone;globalThis.structuredClone=undefined;
 try{const demo=createDemoRuntime();const hosts=demo.getHosts();hosts[0].target='mutated';assert.equal((await (await demo.fetch('/api/state')).json()).hosts[0].target,'gpu-idle-demo')}
 finally{globalThis.structuredClone=previous}
});

test('demo refresh starts at default and can restore it after a manual choice',async()=>{
 const demo=createDemoRuntime();
 assert.equal((await (await demo.fetch('/api/state')).json()).refresh_interval_seconds,30);
 await demo.fetch('/api/settings/refresh',{method:'PUT',body:JSON.stringify({interval_seconds:5})});
 assert.equal((await (await demo.fetch('/api/state')).json()).refresh_interval_seconds,5);
 await demo.fetch('/api/settings/refresh',{method:'PUT',body:JSON.stringify({interval_seconds:null})});
 assert.equal((await (await demo.fetch('/api/state')).json()).refresh_interval_seconds,30);
});
