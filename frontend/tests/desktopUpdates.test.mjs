import test from 'node:test';
import assert from 'node:assert/strict';
import {createDesktopUpdater,nativeUpdateBridge,canRestartForUpdate} from '../src/desktopUpdates.ts';
const snapshot=(phase='idle')=>({supported:true,current_version:'0.1.0',phase,available_version:phase==='idle'?null:'0.1.1',notes:'Changes',downloaded_bytes:50,total_bytes:100,last_checked:1,error:null});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('browser and demo cannot call native bridge',async()=>{
 let calls=0;const target={__TAURI_INTERNALS__:{invoke:()=>{calls++;return Promise.resolve(snapshot())}}};
 assert.equal(nativeUpdateBridge({},false),null);assert.equal(nativeUpdateBridge(target,true),null);
 const updater=createDesktopUpdater(nativeUpdateBridge(target,true));updater.start();await updater.run('install');assert.equal(calls,0);
});
test('startup probes capability once before checking; concurrent requests share the check',async()=>{
 const calls=[];let finish;const updater=createDesktopUpdater(command=>{calls.push(command);return command.endsWith('status')?Promise.resolve(snapshot()):new Promise(resolve=>{finish=resolve})});
 updater.start();updater.start();const work=updater.run('check');await tick();assert.deepEqual(calls,['desktop_update_status','desktop_update_check']);finish(snapshot('available'));await work;assert.equal(updater.getSnapshot().available_version,'0.1.1');
});
test('unsupported debug/platform status never invokes check or install',async()=>{
 const calls=[];const updater=createDesktopUpdater(async command=>{calls.push(command);return {...snapshot(),supported:false}});
 updater.start();await updater.run('check');await updater.run('install');assert.deepEqual(calls,['desktop_update_status']);assert.equal(updater.getSnapshot().supported,false);
});
test('older desktop unknown commands disable all updater actions',async()=>{
 const calls=[];const updater=createDesktopUpdater(async command=>{calls.push(command);throw Error('Command desktop_update_status not found')});
 updater.start();await updater.run('check');await updater.run('install');await updater.run('download');assert.deepEqual(calls,['desktop_update_status']);assert.equal(updater.getSnapshot().supported,false);assert.equal(updater.getSnapshot().error,null);
});
test('manual check also probes capabilities and unsupported errors disable actions',async()=>{
 const calls=[];const updater=createDesktopUpdater(async command=>{calls.push(command);if(command.endsWith('status'))return snapshot();throw Error('Updater is unsupported in debug builds')});
 await updater.run('check');await updater.run('install');assert.deepEqual(calls,['desktop_update_status','desktop_update_check']);assert.equal(updater.getSnapshot().supported,false);
});
test('network/feed failures remain retryable after a successful capability probe',async()=>{
 let fail=true;const updater=createDesktopUpdater(async command=>{if(command.endsWith('status'))return snapshot();if(fail){fail=false;throw Error('404 feed')}return snapshot(command.endsWith('download')?'downloaded':'available')});
 await updater.run('check');assert.equal(updater.getSnapshot().phase,'error');assert.match(updater.getSnapshot().error,/404/);assert.equal(updater.getSnapshot().supported,true);
 await updater.run('check');assert.equal(updater.getSnapshot().phase,'available');await updater.run('download');assert.equal(updater.getSnapshot().phase,'downloaded');
});
test('unsafe work blocks installation after capability probe',async()=>{
 const calls=[];const updater=createDesktopUpdater(async command=>{calls.push(command);return snapshot()},()=>false);await updater.run('install');assert.deepEqual(calls,['desktop_update_status']);assert.equal(updater.getSnapshot().error,'restart_blocked');
 const target=new EventTarget();assert.equal(canRestartForUpdate(target,()=>false),true);target.addEventListener('beforeunload',event=>event.preventDefault());assert.equal(canRestartForUpdate(target,()=>false),false);assert.equal(canRestartForUpdate(new EventTarget(),()=>true),false);
});
test('progress status remains available while a download command is pending',async()=>{
 let finish;const updater=createDesktopUpdater(command=>command.endsWith('download')?new Promise(resolve=>{finish=resolve}):Promise.resolve(snapshot('downloading')));
 const work=updater.run('download');await tick();await updater.run('status');assert.equal(updater.getSnapshot().downloaded_bytes,50);finish(snapshot('downloaded'));await work;assert.equal(updater.getSnapshot().phase,'downloaded');
});
