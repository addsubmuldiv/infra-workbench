import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('native tool window creation runs as an async command to avoid Windows WebView2 deadlock',()=>{
 const source=readFileSync(new URL('../../desktop/src-tauri/src/quick_window.rs',import.meta.url),'utf8');
 assert.match(source,/#\[tauri::command\]\s*pub async fn open_quick_tool\(/);
});
