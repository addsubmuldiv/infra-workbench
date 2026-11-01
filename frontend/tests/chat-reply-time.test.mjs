import test from 'node:test';
import assert from 'node:assert/strict';
import {chatReplyTime} from '../src/agentChat.ts';
const seconds=value=>Date.parse(value)/1000;
test('reply time uses UTC+8 and distinguishes today, earlier dates and earlier years',()=>{
  const now=new Date('2026-11-01T05:00:00Z');
  assert.equal(chatReplyTime(seconds('2026-11-01T04:03:09Z'),now).label,'12:03:09');
  assert.equal(chatReplyTime(seconds('2026-10-31T15:59:59Z'),now).label,'10/31 23:59:59');
  assert.equal(chatReplyTime(seconds('2026-10-31T16:00:00Z'),now).label,'00:00:00');
  assert.equal(chatReplyTime(seconds('2025-11-01T04:03:09Z'),now).label,'2025/11/01 12:03:09');
  const value=chatReplyTime(seconds('2026-11-01T04:03:09Z'),now);
  assert.equal(value.iso,'2026-11-01T04:03:09.000Z');
  assert.match(value.full,/2026\/11\/01 12:03:09/);
  for(const invalid of [0,-1,NaN,Infinity,1e20])assert.equal(chatReplyTime(invalid,now),null);
});
