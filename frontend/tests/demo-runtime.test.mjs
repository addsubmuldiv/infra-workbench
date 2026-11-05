import test from 'node:test';
import assert from 'node:assert/strict';
import {createDemoRuntime,installDemoNetwork} from '../src/demoRuntime.ts';

test('demo owns state and workspace without contacting backend',async()=>{
 const demo=createDemoRuntime();
 const state=await (await demo.fetch('/api/state')).json();
 assert.equal(state.hosts.length,4);assert.equal(state.hosts.filter(h=>h.snapshot.fresh).length,3);
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
 assert.equal(state.reservations[0].status,'ready');assert.equal(state.events.length,1);
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
