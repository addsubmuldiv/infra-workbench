import test from 'node:test';
import assert from 'node:assert/strict';
import {workspaceStorage} from '../src/workspaceState.ts';
import {setLocale} from '../src/i18n.ts';
import {toolText} from '../src/toolI18n.ts';
import {formatBytes} from '../src/internalPolicy.ts';
test('changed capacity errors keep the actual bound in both languages',()=>{
 try{setLocale('en');assert.equal(toolText('日志单行过长（超过 4 B）'),'Log line exceeds 4 B');assert.equal(toolText('文件夹最多支持 2 项'),'Folders support up to 2 items');assert.equal(toolText('请只保留服务器列表：最多 3 台，表格不超过 10 行、4 列'),'Keep only the server list: up to 3 servers, 10 rows and 4 columns');setLocale('zh');assert.equal(toolText('文件夹最多支持 2 项'),'文件夹最多支持 2 项');assert.equal(formatBytes(4),'4 B');}finally{setLocale('zh');workspaceStorage.dispose()}
});

test('streaming errors with changed limits are localized by real API clients',async()=>{
 const {importRequest}=await import('../src/serverImportApi.ts');
 const {skillRequest}=await import('../src/skills.ts');
 const original=globalThis.fetch;
 try{
  setLocale('en');
  globalThis.fetch=async()=>Response.json({detail:'Excel 文件不能超过 8 B'},{status:413});
  await assert.rejects(importRequest('/preview',{method:'POST',body:'123456789'}),/Excel file must not exceed 8 B/);
  await assert.rejects(skillRequest('/import','POST',{},undefined,async()=>Response.json({detail:'导入文件不能超过 8 B'},{status:413})),/Imported files must not exceed 8 B/);
  assert.equal(toolText('日志单行过长（超过 4 B），请先拆分日志'),'Log line exceeds 4 B. Split the log first.');
  assert.equal(toolText('训练记录超过 1 条，请拆分日志后对比；未返回截断结果'),'Training records exceed 1. Split the log before comparing; no truncated result was returned.');
 }finally{globalThis.fetch=original;setLocale('zh');workspaceStorage.dispose()}
});
