import test from 'node:test';
import assert from 'node:assert/strict';
import {terminalRenderer} from '../src/terminalRenderer.ts';

function fixture(loader){
  const addons=[],modes=[];let disposed=0;
  class WebglAddon{onContextLoss(fn){this.loss=fn;return {dispose(){}}}dispose(){disposed++}}
  const renderer=terminalRenderer({loadAddon:addon=>addons.push(addon)},mode=>modes.push(mode),loader??(()=>Promise.resolve({WebglAddon})));
  return {renderer,addons,modes,disposed:()=>disposed};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('only the active terminal owns a WebGL context; hiding preserves the terminal itself',async()=>{
  const f=fixture();f.renderer.setActive(true);await tick();assert.equal(f.addons.length,1);
  f.renderer.setActive(true);await tick();assert.equal(f.addons.length,1);
  f.renderer.setActive(false);assert.equal(f.disposed(),1);assert.equal(f.modes.at(-1),'dom');
  f.renderer.setActive(true);await tick();assert.equal(f.addons.length,2);f.renderer.dispose();assert.equal(f.disposed(),2);
});
test('context loss and unavailable GPUs retain DOM rendering without retry loops',async()=>{
  const f=fixture();f.renderer.setActive(true);await tick();f.addons[0].loss();
  assert.equal(f.disposed(),1);assert.equal(f.modes.at(-1),'dom');f.renderer.setActive(true);await tick();assert.equal(f.addons.length,1);
  const unavailable=fixture(()=>Promise.reject(new Error('unsupported WebGL')));unavailable.renderer.setActive(true);await tick();assert.equal(unavailable.modes.at(-1),'dom');
});
test('a pending import cannot attach a GPU renderer after tab switch or unmount',async()=>{
  let resolve;const f=fixture(()=>new Promise(done=>{resolve=done}));f.renderer.setActive(true);f.renderer.dispose();
  resolve({WebglAddon:class{}});await tick();assert.equal(f.addons.length,0);
});
test('an unsupported WebView constructor and renderer initialization failures fall back safely',async()=>{
  const unsupported=fixture(()=>Promise.resolve({WebglAddon:class{constructor(){throw new Error('Safari version unsupported')}}}));
  unsupported.renderer.setActive(true);await tick();assert.equal(unsupported.modes.at(-1),'dom');
  let disposed=0;const modes=[];
  const renderer=terminalRenderer({loadAddon(){throw new Error('GPU initialization failed')}},mode=>modes.push(mode),()=>Promise.resolve({WebglAddon:class{onContextLoss(){return {dispose(){}}}dispose(){disposed++}}}));
  renderer.setActive(true);await tick();assert.equal(disposed,1);assert.equal(modes.at(-1),'dom');renderer.dispose();assert.equal(disposed,1);
});
