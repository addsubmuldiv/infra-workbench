import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadPreferences, savePreferences, toggleHost, scopedHosts, THEMES} from '../src/preferences.ts';

function storage(){const map=new Map();return {getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value)}}
test('theme and a multi-machine selection survive reopening',()=>{
  const disk=storage();
  savePreferences(disk,{theme:'paper',hostIds:['one','three']});
  const next=loadPreferences(disk);
  assert.deepEqual(next,{theme:'paper',hostIds:['one','three']});
  assert.deepEqual(scopedHosts([{id:'one'},{id:'two'},{id:'three'}],next.hostIds).map(h=>h.id),['one','three']);
});
test('all, empty, and a missing remembered machine remain distinct',()=>{
  const hosts=[{id:'one'},{id:'two'}];
  assert.equal(scopedHosts(hosts,null).length,2);
  assert.equal(scopedHosts(hosts,[]).length,0);
  assert.equal(scopedHosts(hosts,['deleted']).length,0);
  assert.deepEqual(toggleHost(null,'one',hosts.map(h=>h.id)),['two']);
  assert.deepEqual(toggleHost(['one'],'two',['one','two']),['one','two']);
});
test('invalid stored settings fall back and storage errors do not crash the app',()=>{
  assert.deepEqual(loadPreferences({getItem:()=>'{broken'}),{theme:'daylight',hostIds:null});
  assert.deepEqual(loadPreferences({getItem:()=>JSON.stringify({theme:'unknown',hostIds:123})}),{theme:'daylight',hostIds:null});
  assert.equal(savePreferences({setItem:()=>{throw Error('quota')}},{theme:'daylight',hostIds:[]}),false);
});
test('Solid Glass variants can be restored with the existing machine selection',()=>{
  const disk=storage();
  for(const [theme,mode] of [['glass-light','light'],['glass-dark','dark'],['glass-jade','light'],['glass-dusk','dark'],['glass-white','light'],['glass-black','dark']]){
    assert.equal(THEMES.find(option=>option.id===theme)?.mode,mode);
    const preferences={theme,hostIds:['one']};
    assert.equal(savePreferences(disk,preferences),true);
    assert.deepEqual(loadPreferences(disk),preferences);
  }
});
