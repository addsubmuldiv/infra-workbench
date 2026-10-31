import {EditorState,Transaction} from '@codemirror/state';
import type {EditorView} from '@codemirror/view';
import {getSearchQuery} from '@codemirror/search';

type ClipboardIO=Pick<Clipboard,'readText'|'writeText'>;
const selectedText=(state:EditorState)=>state.selection.ranges.map(range=>state.sliceDoc(range.from,range.to)).filter(Boolean).join('\n');
const unchanged=(view:EditorView,before:EditorState)=>view.state.doc===before.doc&&view.state.selection.eq(before.selection);
export async function copyText(view:EditorView,clipboard:ClipboardIO=navigator.clipboard){
  const text=selectedText(view.state);if(!text)return false;
  await clipboard.writeText(text);return true;
}
export async function cutText(view:EditorView,clipboard:ClipboardIO=navigator.clipboard){
  const before=view.state;if(before.readOnly||!selectedText(before))return false;
  await copyText(view,clipboard);
  if(!unchanged(view,before)||view.state.readOnly)throw new Error('编辑内容或选择已变化，请重新剪切');
  view.dispatch({...view.state.replaceSelection(''),annotations:Transaction.userEvent.of('delete.cut'),scrollIntoView:true});return true;
}
export async function pasteText(view:EditorView,clipboard:ClipboardIO=navigator.clipboard){
  const before=view.state;if(before.readOnly)return false;
  const text=await clipboard.readText();if(!text)return false;
  if(!unchanged(view,before)||view.state.readOnly)throw new Error('编辑内容或选择已变化，请重新粘贴');
  view.dispatch({...view.state.replaceSelection(text),annotations:Transaction.userEvent.of('input.paste'),scrollIntoView:true});return true;
}
export function searchMatchCount(state:EditorState,limit=10000){
  const query=getSearchQuery(state);if(!query.search)return '';
  if(!query.valid)return '无效的正则表达式';
  const cursor=query.getCursor(state.doc);let count=0;
  while(!cursor.next().done){count++;if(count>limit)return '超过 '+limit+' 处匹配'}
  return count+' 处匹配';
}
