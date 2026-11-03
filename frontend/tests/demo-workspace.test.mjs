import test from 'node:test';
import assert from 'node:assert/strict';
import {initializeWorkspace,workspaceStorage} from '../src/workspaceState.ts';

test('isolated workspace never reads or removes real legacy browser preferences',async()=>{
 const oldWindow=globalThis.window,oldFetch=globalThis.fetch;let touched=0;let timer;
 globalThis.window={get localStorage(){touched++;throw new Error('real storage accessed')},setInterval(){return 0},addEventListener(){},dispatchEvent(){}};
 globalThis.fetch=async()=>new Response(JSON.stringify({revision:0,values:{}}),{headers:{'Content-Type':'application/json'}});
 try{await initializeWorkspace({isolated:true});assert.equal(touched,0);assert.equal(workspaceStorage.getItem('real-key'),null)}
 finally{workspaceStorage.dispose();globalThis.window=oldWindow;globalThis.fetch=oldFetch}
});
