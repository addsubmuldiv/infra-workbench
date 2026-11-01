import test from 'node:test';
import assert from 'node:assert/strict';
import {skillMention} from '../src/skillMention.ts';
test('skill mentions match the cursor and preserve surrounding prose',()=>{
  assert.deepEqual(skillMention('检查 @read 后续',8),{start:3,end:8,query:'read'});
  assert.deepEqual(skillMention('@',1),{start:0,end:1,query:''});
  assert.deepEqual(skillMention('检查@read',7),{start:2,end:7,query:'read'});
  assert.deepEqual(skillMention('检查\n@日志',6),{start:3,end:6,query:'日志'});
});
test('email addresses and completed mentions do not open the menu',()=>{
  assert.equal(skillMention('user@example.com',16),null);
  assert.equal(skillMention('@read ',6),null);
  assert.equal(skillMention('hello',5),null);
});
