import test from 'node:test';
import assert from 'node:assert/strict';
import {EditorState} from '@codemirror/state';
import {history,undo,redo} from '@codemirror/commands';
import {search,SearchQuery,setSearchQuery} from '@codemirror/search';
import {copyText,cutText,pasteText,searchMatchCount} from '../src/textEditorActions.ts';

function editor(doc,from=0,to=from,readOnly=false){
  const view={state:EditorState.create({doc,selection:{anchor:from,head:to},extensions:[history(),search(),EditorState.readOnly.of(readOnly)]}),dispatch(spec){view.state=view.state.update(spec).state}};
  view.dispatch=view.dispatch.bind(view);return view;
}
test('copy and cut preserve literal selected text; cut and paste can be undone and redone',async()=>{
  const view=editor('中文\nsecond',0,2);let text='';const clipboard={async writeText(value){text=value},async readText(){return '粘贴\r\ntext'}};
  await copyText(view,clipboard);assert.equal(text,'中文');assert.equal(view.state.doc.toString(),'中文\nsecond');
  await cutText(view,clipboard);assert.equal(view.state.doc.toString(),'\nsecond');
  assert.ok(undo(view));assert.equal(view.state.doc.toString(),'中文\nsecond');
  assert.ok(redo(view));assert.equal(view.state.doc.toString(),'\nsecond');
  await pasteText(view,clipboard);assert.equal(view.state.doc.toString(),'粘贴\ntext\nsecond');
  assert.ok(undo(view));assert.equal(view.state.doc.toString(),'\nsecond');
});
test('clipboard failures, changed selection and read-only mode never delete or overwrite text',async()=>{
  const view=editor('safe',0,4),clipboard={async writeText(){throw new Error('denied')},async readText(){view.dispatch({selection:{anchor:0}});return 'overwrite'}};
  await assert.rejects(cutText(view,clipboard),/denied/);assert.equal(view.state.doc.toString(),'safe');
  await assert.rejects(pasteText(view,clipboard),/选择已变化/);assert.equal(view.state.doc.toString(),'safe');
  const locked=editor('locked',0,6,true);assert.equal(await cutText(locked,clipboard),false);assert.equal(await pasteText(locked,clipboard),false);
});
test('matching count follows case, whole-word and invalid-regex settings with a bounded count',()=>{
  const view=editor('Model model models [x]');
  const query=options=>{view.dispatch({effects:setSearchQuery.of(new SearchQuery(options))});return searchMatchCount(view.state)};
  assert.equal(query({search:'model'}),'3 处匹配');
  assert.equal(query({search:'model',caseSensitive:true,wholeWord:true}),'1 处匹配');
  assert.equal(query({search:'[x]'}),'1 处匹配');assert.equal(query({search:'[',regexp:true}),'无效的正则表达式');
  view.dispatch({effects:setSearchQuery.of(new SearchQuery({search:'m'}))});assert.equal(searchMatchCount(view.state,1),'超过 1 处匹配');
});
