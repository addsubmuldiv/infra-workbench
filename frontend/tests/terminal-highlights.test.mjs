import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readHighlights,HIGHLIGHTS_KEY,normalizeHighlights,matchHighlightLine,createTerminalHighlights,DEFAULT_HIGHLIGHTS} from '../src/terminalHighlights.ts';
const cells=text=>Array.from(text).flatMap(c=>c==='中'?[{getChars:()=>c,getWidth:()=>2},{getChars:()=>'',getWidth:()=>0}]:[{getChars:()=>c,getWidth:()=>1}]);
const line=text=>{const c=cells(text);return {length:c.length,getCell:i=>c[i]}};
test('literal rules map wide Unicode columns and ignore disabled rules',()=>{
 const prefs=normalizeHighlights({enabled:true,rules:[{text:'NaN',color:'#ff0000',enabled:true},{text:'.*',color:'#00ff00',enabled:true}]});
 assert.deepEqual(matchHighlightLine(line('中NaN .*'),prefs.rules),[{x:2,width:3,color:'#ff0000'},{x:6,width:2,color:'#00ff00'}]);
 assert.deepEqual(matchHighlightLine(line('NaN'),[{text:'NaN',color:'#ff0000',enabled:false}]),[]);
});
test('validates untrusted saved rules, bounds text and rule count',()=>{
 assert.equal(normalizeHighlights({enabled:true,rules:Array(50).fill({text:'x',color:'#123456',enabled:true})}).rules.length,20);
 assert.deepEqual(normalizeHighlights({rules:[{text:'\u001b',color:'red'},{text:'x'.repeat(129),color:'#123456'}]}).rules,[]);
 assert.ok(DEFAULT_HIGHLIGHTS.rules.some(r=>r.text==='checkpoint'&&r.color==='#166534'));
});
test('controller bounds visible reads/decorations, cleans resources and skips alternate buffer',()=>{
 let alternate=false,reads=0,disposed=0;const listeners={};
 const normal={type:'normal',viewportY:20,baseY:20,cursorY:1,getLine:()=>{reads++;return line('NaN '.repeat(500))}};
 const term={rows:1000,cols:2000,buffer:{get active(){return alternate?{...normal,type:'alternate'}:normal}},registerMarker:()=>({dispose(){disposed++}}),registerDecoration:()=>({dispose(){disposed++}}),onRender:fn=>{listeners.render=fn;return {dispose(){}}},onScroll:fn=>({dispose(){}}),onWriteParsed:fn=>{listeners.write=fn;return {dispose(){}}}};
 const controller=createTerminalHighlights(term,()=>normalizeHighlights({enabled:true,rules:[{text:'NaN',enabled:true,color:'#ff0000'}]}));
 controller.refresh();assert.ok(reads<=200);assert.ok(controller.count()<=400);assert.ok(controller.count()>0);
 const previous=disposed;listeners.write();controller.refresh();assert.ok(disposed>previous,"parsed writes invalidate markers even when capped scrollback coordinates and visible text stay identical");
 alternate=true;controller.refresh();assert.equal(controller.count(),0);assert.ok(disposed>0);controller.dispose();
});

test('saved workspace preferences retain master switch and custom text/color/enabled values',()=>{
 const saved={enabled:false,rules:[{text:'训练完成',color:'#166534',enabled:false}]};
 assert.deepEqual(readHighlights({getItem:key=>key===HIGHLIGHTS_KEY?JSON.stringify(saved):null}),saved);
 assert.deepEqual(readHighlights({getItem:()=>'{broken'}),DEFAULT_HIGHLIGHTS);
});
