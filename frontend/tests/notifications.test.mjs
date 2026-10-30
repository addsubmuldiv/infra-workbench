import test from 'node:test';
import assert from 'node:assert/strict';
import {shouldNotify} from '../src/notifications.ts';

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
