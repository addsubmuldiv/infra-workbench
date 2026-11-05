import test from 'node:test';
import assert from 'node:assert/strict';
import {workspaceStorage} from '../src/workspaceState.ts';
import {setLocale} from '../src/i18n.ts';
import {toolText} from '../src/toolI18n.ts';
import {formatBytes} from '../src/internalPolicy.ts';
test('changed capacity errors keep the actual bound in both languages',()=>{
 try{setLocale('en');assert.equal(toolText('日志单行过长（超过 4 B）'),'Log line exceeds 4 B');assert.equal(toolText('文件夹最多支持 2 项'),'Folders support up to 2 items');assert.equal(toolText('请只保留服务器列表：最多 3 台，表格不超过 10 行、4 列'),'Keep only the server list: up to 3 servers, 10 rows and 4 columns');setLocale('zh');assert.equal(toolText('文件夹最多支持 2 项'),'文件夹最多支持 2 项');assert.equal(formatBytes(4),'4 B');}finally{setLocale('zh');workspaceStorage.dispose()}
});
