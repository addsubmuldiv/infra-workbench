import test from 'node:test';
import assert from 'node:assert/strict';
import {loadChatId,saveChatId,toolNames,toolStatus} from '../src/agentChat.ts';

test('browser persistence stores only the opaque chat ID and ignores invalid IDs',t=>{
  const old=Object.getOwnPropertyDescriptor(globalThis,'localStorage');const values=new Map();
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)}});
  t.after(()=>old?Object.defineProperty(globalThis,'localStorage',old):delete globalThis.localStorage);
  saveChatId('a'.repeat(32));assert.equal(loadChatId(),'a'.repeat(32));
  values.set('iwb-assistant-chat','../invalid');assert.equal(loadChatId(),null);
  assert.deepEqual([...values.keys()],['iwb-assistant-chat']);
});
test('failed tools are labelled as incomplete and SSH operations have a user-facing label',()=>{
  assert.equal(toolStatus.failed,'未完成');assert.equal(toolStatus.cancelled,'已取消');
  assert.equal(toolNames.ssh_check,'SSH 只读检查');
});
