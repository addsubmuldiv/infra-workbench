import test from 'node:test';
import assert from 'node:assert/strict';
import {waitSeconds,loadWaitMinutes,saveWaitMinutes,countdown,reservationDraft,reservationLocation,desktopStatusText} from '../src/reservations.ts';

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

test('editing restores every condition while reserve again creates a fresh record',()=>{
  const item={id:'booking',host_id:'machine / A',devices:['1','3'],minimum_gib:24,mode:'fixed',wait_seconds:180,email_notify:true};
  assert.deepEqual(reservationDraft(item,true),{hostId:'machine / A',devices:['1','3'],minimum:24,mode:'fixed',waitSeconds:180,emailNotify:true,requiredCount:undefined,kind:undefined,editingId:'booking'});
  const again=reservationDraft({...item,mode:'count',required_count:3,kind:'NPU',devices:[]},false);
  assert.equal(again.editingId,undefined);
  assert.equal(again.requiredCount,3);
  assert.equal(again.emailNotify,true);
  again.devices.push('external');
  assert.deepEqual(item.devices,['1','3']);
});

test('count reminders link the exact devices that satisfied the condition',()=>{
  const link=reservationLocation({host_id:'machine / A',mode:'count',devices:[],matched_devices:['0/1','2']});
  assert.equal(link,'#overview?host=machine+%2F+A&device=0%2F1&device=2');
  assert.match(desktopStatusText.submitted,/提交/);
  assert.doesNotMatch(desktopStatusText.submitted,/送达|收到/);
});
