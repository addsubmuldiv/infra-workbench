import test from 'node:test';
import assert from 'node:assert/strict';
import {loadChatId,saveChatId,toolNames,toolStatus,permissionScope,applyChatEvent,parseExternalMcpServers} from '../src/agentChat.ts';

test('browser persistence stores only the opaque chat ID and ignores invalid IDs',t=>{
  const old=Object.getOwnPropertyDescriptor(globalThis,'localStorage');const values=new Map();
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)}});
  t.after(()=>old?Object.defineProperty(globalThis,'localStorage',old):delete globalThis.localStorage);
  saveChatId('a'.repeat(32),localStorage);assert.equal(loadChatId(localStorage),'a'.repeat(32));
  values.set('iwb-assistant-chat','../invalid');assert.equal(loadChatId(localStorage),null);
  assert.deepEqual([...values.keys()],['iwb-assistant-chat']);
});
test('failed tools are labelled as incomplete and SSH operations have a user-facing label',()=>{
  assert.equal(toolStatus.failed,'未完成');assert.equal(toolStatus.cancelled,'已取消');
  assert.equal(toolNames.ssh_check,'SSH 只读检查');
});


test('permission scopes retain explicit local and selected server roots',()=>{
  assert.deepEqual(permissionScope('ask',' C:/project\nC:/project\n\n D:/data ','/srv/project\r\n/srv/data',['host-a','host-b']),{permission_mode:'ask',local_roots:['C:/project','D:/data'],remote_roots:{'host-a':['/srv/project','/srv/data'],'host-b':['/srv/project','/srv/data']},external_mcp_servers:[]});
  assert.deepEqual(permissionScope('read_only','','/srv/project',[]),{permission_mode:'read_only',local_roots:[],remote_roots:{},external_mcp_servers:[]});
});

test('approval status reaches the current assistant turn through delta events',()=>{
 const chat={id:'chat',title:'test',created:1,updated:2,active_run:'run',turns:[{id:'turn',role:'assistant',content:'',created:1}]};
 const approval={id:'approval',run_id:'run',tool:'Shell',arguments:{command:'pwd'},reason:'Needs approval',status:'pending',created:2};
 const pending=applyChatEvent(chat,{type:'patch',data:{chat_id:'chat',title:'test',updated:3,base_updated:2,active_run:'run',turn_id:'turn',changes:{approvals:[approval]}}});
 assert.equal(pending.turns[0].approvals[0].status,'pending');
 const approved=applyChatEvent(pending,{type:'patch',data:{chat_id:'chat',title:'test',updated:4,base_updated:3,active_run:'run',turn_id:'turn',changes:{approvals:[{...approval,status:'approved',decision:'approve'}]}}});
 assert.equal(approved.turns[0].approvals[0].status,'approved');
 assert.equal(approved.turns[0].content,'');
});


test('external MCP configuration accepts explicit HTTP services and rejects malformed definitions',()=>{
 assert.deepEqual(parseExternalMcpServers('research https://example.com/mcp\nlocal http://127.0.0.1:8000/mcp'),[{name:'research',url:'https://example.com/mcp'},{name:'local',url:'http://127.0.0.1:8000/mcp'}]);
 assert.deepEqual(parseExternalMcpServers(''),[]);
 for(const value of ['bad.name https://example.com/mcp','1bad https://example.com/mcp','a stdio://server','a https://user:secret@example.com/mcp','a https://example.com/mcp\na https://example.com/other','a https://a/mcp\nb https://b/mcp\nc https://c/mcp\nd https://d/mcp'])assert.throws(()=>parseExternalMcpServers(value));
 assert.deepEqual(permissionScope('ask','','',[],'research https://example.com/mcp').external_mcp_servers,[{name:'research',url:'https://example.com/mcp'}]);
});
