import test from 'node:test';
import assert from 'node:assert/strict';
import {browserId} from '../src/browserId.ts';

test('native UUID remains the fast path with its original receiver',()=>{
  const source={randomUUID(){assert.equal(this,source);return 'native-id'},getRandomValues(){throw new Error('unused')}};
  assert.equal(browserId(source),'native-id');
});
test('older secure WebViews without randomUUID generate a v4 ID from crypto bytes',()=>{
  let calls=0;
  const id=browserId({getRandomValues(bytes){calls++;bytes.fill(255);return bytes}});
  assert.equal(calls,1);assert.equal(id,'ffffffff-ffff-4fff-bfff-ffffffffffff');
});
