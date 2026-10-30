import test from 'node:test';
import assert from 'node:assert/strict';
import {waitSeconds,loadWaitMinutes,saveWaitMinutes,countdown} from '../src/reservations.ts';

test('idle waiting defaults to two minutes and safely restores a custom value',()=>{
  assert.equal(loadWaitMinutes(null),2);
  for(const raw of [null,'','NaN','Infinity','-1','1441'])assert.equal(loadWaitMinutes({getItem:()=>raw}),2);
  let saved=null;
  saveWaitMinutes({setItem:(_,value)=>{saved=value}},3.5);
  assert.equal(loadWaitMinutes({getItem:()=>saved}),3.5);
  assert.equal(waitSeconds(3.5),210);
  assert.equal(waitSeconds(0),0);
  assert.throws(()=>waitSeconds(-1));
  assert.throws(()=>waitSeconds(Infinity));
  assert.equal(loadWaitMinutes({getItem:()=>{throw new Error('blocked')}}),2);
});
test('remaining time never shows negative values and rounds up partial seconds',()=>{
  assert.equal(countdown(-1),'0 秒');
  assert.equal(countdown(0.1),'1 秒');
  assert.equal(countdown(120),'2 分 0 秒');
});
