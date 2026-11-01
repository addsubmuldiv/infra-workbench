import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkspaceStorage} from '../src/workspaceState.ts';
function server(){let state={revision:0,values:{}};return async(values,missing)=>{if(values){const next={...state.values};for(const [k,v] of Object.entries(values)){if(missing&&k in next)continue;if(v===null)delete next[k];else next[k]=v}state={revision:state.revision+1,values:next}}return structuredClone(state)}}
test('separate clients share changes without overwriting unrelated keys',async t=>{
 const send=server(),a=createWorkspaceStorage(send),b=createWorkspaceStorage(send);t.after(()=>{a.dispose();b.dispose()});
 await a.initialize();await b.initialize();let updates=0;b.subscribe('theme',()=>updates++);
 a.setItem('theme','dark');b.setItem('width','300');await a.flush();await b.flush();await a.refresh();await b.refresh();
 assert.equal(a.getItem('width'),'300');assert.equal(b.getItem('theme'),'dark');assert.equal(updates,1);
});
test('an edit made during a pending save survives the earlier response',async t=>{
 const send=server();let release;let delayed=false;
 const a=createWorkspaceStorage(async(...args)=>{const value=await send(...args);if(delayed)await new Promise(resolve=>release=resolve);return value});t.after(()=>a.dispose());
 await a.initialize();delayed=true;a.setItem('draft','one');const flight=a.flush();await new Promise(resolve=>setImmediate(resolve));a.setItem('draft','two');release();await flight;assert.equal(a.getItem('draft'),'two');delayed=false;await a.flush();assert.equal((await send()).values.draft,'two');
});
test('failed saves retain local edits and retry on reconnect',async t=>{
 const send=server();let offline=false;const failures=[];const a=createWorkspaceStorage((...args)=>{if(offline)throw Error('offline');return send(...args)},failed=>failures.push(failed));t.after(()=>a.dispose());
 await a.initialize();offline=true;a.setItem('draft','keep');await a.flush();assert.equal(a.getItem('draft'),'keep');assert.equal(a.hasUnsaved(),true);offline=false;await a.refresh();assert.equal((await send()).values.draft,'keep');assert.equal(failures.at(-1),false);
});
test('a later browser cannot overwrite the shared theme during migration',async t=>{
 const send=server(),a=createWorkspaceStorage(send),b=createWorkspaceStorage(send);t.after(()=>{a.dispose();b.dispose()});
 const key='infra-workbench:preferences:v1';await a.initialize({getItem:k=>k===key?'first':null});await b.initialize({getItem:k=>k===key?'second':null});assert.equal(b.getItem(key),'first');
});
