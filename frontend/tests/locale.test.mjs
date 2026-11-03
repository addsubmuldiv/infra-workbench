import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createLocaleStore,localized,readLocale,LOCALE_KEY} from '../src/localeStore.ts';
test('Chinese is the compatible default and invalid saved values are rejected',()=>{
 for(const value of [null,'','fr','"en"'])assert.equal(readLocale(value),'zh');
 assert.equal(readLocale('en'),'en');
});
test('language changes persist and notify open consumers without resetting their state',()=>{
 const data=new Map(),listeners=new Set();
 const storage={getItem:key=>data.get(key)??null,setItem:(key,value)=>{data.set(key,value);for(const fn of listeners)fn()},subscribe:(key,fn)=>{assert.equal(key,LOCALE_KEY);listeners.add(fn);return()=>listeners.delete(fn)}};
 const store=createLocaleStore(storage);let updates=0;const stop=store.subscribe(()=>updates++);
 store.setLocale('en');assert.equal(updates,1);assert.equal(store.getSnapshot(),'en');assert.equal(createLocaleStore(storage).getSnapshot(),'en');
 assert.equal(localized(store.getSnapshot(),'设置','Settings'),'Settings');
 store.setLocale('zh');assert.equal(localized(store.getSnapshot(),'设置','Settings'),'设置');
 assert.throws(()=>store.setLocale('fr'));stop();assert.equal(listeners.size,0);
});
test('translations preserve placeholders, paths and command text exactly',()=>{
 const name='server-中文 /tmp/实验 $HOME';
 assert.equal(localized('en',`打开 ${name}`,`Open ${name}`),`Open ${name}`);
});
