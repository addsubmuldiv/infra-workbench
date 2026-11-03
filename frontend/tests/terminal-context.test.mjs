import {test} from 'node:test';
import assert from 'node:assert/strict';
import {captureTerminal} from '../src/terminalContext.ts';
test('capture bounds Unicode text and strips terminal controls',()=>{
 const terminal={getSelection:()=>('😀\u0007\r\n').repeat(200),rows:24,buffer:{active:{viewportY:0,getLine:()=>undefined}}};
 const result=captureTerminal(terminal,{host_id:'a',label:'node',terminal_id:'tab'},'selection');
 assert.equal(result.content.split('\n').length,150);assert.equal(result.truncated,true);assert.ok(!result.content.includes('\u0007'));assert.ok(!/[\uD800-\uDBFF]$/.test(result.content));
});
test('screen captures viewport only, never sends input',()=>{
 const reads=[]; const terminal={getSelection:()=>'',rows:2,buffer:{active:{viewportY:4,getLine:i=>{reads.push(i);return {translateToString:()=>`line ${i}`}}}}};
 assert.equal(captureTerminal(terminal,{host_id:'a',label:'node',terminal_id:'tab'},'screen').content,'line 4\nline 5');assert.deepEqual(reads,[4,5]);
});
