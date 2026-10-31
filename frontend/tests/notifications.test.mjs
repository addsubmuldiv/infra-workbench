import test from 'node:test';
import assert from 'node:assert/strict';
import {shouldNotify,loadReadEvent,saveReadEvent,unreadEvents} from '../src/notifications.ts';

test('SSH and collection failures or recovery are silent in browser notifications',()=>{
  for(const message of ['test-host：SSH 连接失败','test-host：采集已恢复','test-host：已连接，远端采集失败','test-host：已连接，设备解析失败'])
    assert.equal(shouldNotify({message,created:1000},1000),false);
});

test('resource changes stay enabled, stale or explicitly silent events are skipped',()=>{
  const message='test-host · 卡 0：资源恢复，满足监控条件';
  assert.equal(shouldNotify({message,created:1000},1001),true);
  assert.equal(shouldNotify({message,created:1},1000),false);
  assert.equal(shouldNotify({message,created:1000,notify:false},1000),false);
  assert.equal(shouldNotify({message:'test-host：设备编号已变化，请重新选择监控设备',created:1000},1000),true);
});

test('unread badge counts resource messages, not silent connection history, and survives reload',()=>{
  const storage=new Map(),store={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)};
  const events=[{id:5,message:'a：SSH 连接失败',created:1},{id:4,message:'a：采集已恢复',created:1},{id:3,message:'a：预约可用',created:1},{id:2,message:'a：内部记录',created:1,notify:false}];
  // notify is delivery eligibility, including expiry; it is not a read receipt.
  assert.equal(loadReadEvent(store),0);assert.equal(unreadEvents(events,0),2);
  assert.equal(saveReadEvent(store,5),true);assert.equal(unreadEvents(events,loadReadEvent(store)),0);
  assert.equal(unreadEvents([{id:6,message:'新的预约提醒',created:2},...events],loadReadEvent(store)),1);
});

test('notification read state tolerates unavailable or corrupt browser storage',()=>{
  assert.equal(loadReadEvent(null),0);assert.equal(saveReadEvent(null,4),false);
  for(const value of ['bad','-1','Infinity','1.5'])assert.equal(loadReadEvent({getItem:()=>value}),0);
  const denied={getItem(){throw Error('denied')},setItem(){throw Error('denied')}};
  assert.equal(loadReadEvent(denied),0);assert.equal(saveReadEvent(denied,4),false);
});
