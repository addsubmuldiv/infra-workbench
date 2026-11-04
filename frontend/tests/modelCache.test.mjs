import test from 'node:test';
import assert from 'node:assert/strict';
import {readModelCache,writeModelCache,modelCacheKey,MODEL_CACHE_TTL} from '../src/modelCache.ts';

test('model lists persist for 14 days and remain available when stale',()=>{
  const values=new Map();
  const storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};
  const config={active_id:'one',base_url:'https://example.test/v1',protocol:'auto'};
  const key=modelCacheKey(config);
  writeModelCache(key,{models:['a'],truncated:false},storage,100);
  assert.deepEqual(readModelCache(key,storage,101),{models:['a'],truncated:false,stale:false});
  assert.equal(MODEL_CACHE_TTL,14*24*60*60*1000);
  assert.equal(readModelCache(key,storage,100+MODEL_CACHE_TTL).stale,true);
  assert.equal(readModelCache(modelCacheKey({...config,active_id:'two'}),storage),null);
  assert.equal(readModelCache(modelCacheKey({...config,base_url:'https://other.test'}),storage),null);
  storage.setItem(key,'broken');
  assert.equal(readModelCache(key,storage),null);
});
