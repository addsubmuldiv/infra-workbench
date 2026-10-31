import React,{useEffect,useRef,useState} from 'react';
import {Compartment,EditorState,Transaction} from '@codemirror/state';
import {EditorView,drawSelection,highlightActiveLine,keymap,lineNumbers} from '@codemirror/view';
import {defaultKeymap,history,historyKeymap,indentWithTab,redo,redoDepth,selectAll,undo,undoDepth} from '@codemirror/commands';
import {closeSearchPanel,getSearchQuery,gotoLine,highlightSelectionMatches,openSearchPanel,search,searchKeymap} from '@codemirror/search';
import {Copy,Scissors,ClipboardPaste,Undo2,Redo2,Search,Replace,WrapText,ListOrdered,TextSelect} from 'lucide-react';
import {copyText,cutText,pasteText,searchMatchCount} from './textEditorActions';

const phrases={Find:'查找',Replace:'替换',next:'下一处',previous:'上一处',all:'选中全部匹配','match case':'区分大小写',regexp:'正则表达式','by word':'全字匹配',replace:'替换当前','replace all':'全部替换',close:'关闭查找','Go to line':'跳转到行',go:'跳转','replaced $ matches':'已替换 $ 处匹配','replaced match on line $':'已替换第 $ 行的匹配','current match':'当前匹配','on line':'所在行'};
const editorTheme=EditorView.theme({
  '&':{height:'100%',backgroundColor:'var(--input)',color:'var(--text)',fontSize:'13px'},
  '&.cm-focused':{outline:'none'},'.cm-scroller':{fontFamily:'Consolas,"Cascadia Mono",monospace',lineHeight:'1.7',overflow:'auto'},
  '.cm-content':{padding:'12px 0',caretColor:'var(--accent)'},'.cm-line':{padding:'0 12px'},
  '.cm-gutters':{backgroundColor:'var(--panel2)',color:'var(--muted)',borderColor:'var(--line)'},
  '.cm-activeLine,.cm-activeLineGutter':{backgroundColor:'var(--accent-bg)'},
  '&.cm-focused .cm-selectionBackground,.cm-selectionBackground,::selection':{backgroundColor:'var(--accent-bg)'},
  '.cm-cursor':{borderLeftColor:'var(--accent)'},'.cm-searchMatch':{backgroundColor:'#e8b94944',outline:'1px solid #b98a36'},
  '.cm-searchMatch-selected':{backgroundColor:'#e8b94988'},'.cm-selectionMatch':{backgroundColor:'var(--accent-bg)'},
  '.cm-panels':{backgroundColor:'var(--panel2)',color:'var(--text)'},'.cm-panels-top':{borderBottomColor:'var(--line)'},
});
const openReplace=(view:EditorView)=>{openSearchPanel(view);view.dom.querySelector<HTMLInputElement>('input[name="replace"]')?.focus();return true};

export function TextEditor({value,onChange,readOnly}:{value:string;onChange:(value:string)=>void;readOnly:boolean}){
  const element=useRef<HTMLDivElement>(null),editor=useRef<EditorView|null>(null),onChangeRef=useRef(onChange);onChangeRef.current=onChange;
  const editable=useRef(new Compartment()),wrapping=useRef(new Compartment());
  const [wrap,setWrap]=useState(false),[message,setMessage]=useState('');
  const [info,setInfo]=useState({line:1,column:1,selected:0,undo:false,redo:false,matches:''});
  useEffect(()=>{
    let alive=true;
    const updateInfo=(state:EditorState,matches?:string)=>{const selection=state.selection.main,line=state.doc.lineAt(selection.head);
      setInfo(old=>({line:line.number,column:selection.head-line.from+1,selected:state.selection.ranges.reduce((sum,r)=>sum+r.to-r.from,0),undo:undoDepth(state)>0,redo:redoDepth(state)>0,matches:matches??old.matches}))};
    const view=new EditorView({parent:element.current!,state:EditorState.create({doc:value,extensions:[
      lineNumbers(),drawSelection(),highlightActiveLine(),history(),highlightSelectionMatches(),search({top:true}),EditorState.phrases.of(phrases),editorTheme,
      editable.current.of(EditorState.readOnly.of(readOnly)),wrapping.current.of([]),
      EditorView.contentAttributes.of({'aria-label':'文件文本内容',spellcheck:'false'}),
      keymap.of([{key:'Mod-h',run:openReplace,scope:'editor search-panel',preventDefault:true},{key:'Escape',run:closeSearchPanel,scope:'editor search-panel'},...searchKeymap,...historyKeymap,...defaultKeymap,indentWithTab]),
      EditorView.updateListener.of(update=>{if(!alive)return;if(update.docChanged)onChangeRef.current(update.state.doc.toString());
        const queryChanged=!getSearchQuery(update.startState).eq(getSearchQuery(update.state));
        const matches=update.docChanged||queryChanged?searchMatchCount(update.state):undefined;
        updateInfo(update.state,matches);
      }),
    ]})});
    // The built-in search panel commits on keyup/change. Also commit input so
    // mouse paste and browser autofill take effect before clicking Replace.
    const searchInput=(event:Event)=>{if(event.target instanceof HTMLInputElement&&event.target.closest('.cm-search'))event.target.dispatchEvent(new Event('change',{bubbles:true}))};
    view.dom.addEventListener('input',searchInput);
    editor.current=view;updateInfo(view.state,'');
    return()=>{alive=false;editor.current=null;view.dom.removeEventListener('input',searchInput);view.destroy()};
  },[]);
  useEffect(()=>{const view=editor.current;if(view&&view.state.doc.toString()!==value)view.dispatch({changes:{from:0,to:view.state.doc.length,insert:value},annotations:Transaction.addToHistory.of(false)})},[value]);
  useEffect(()=>{editor.current?.dispatch({effects:editable.current.reconfigure(EditorState.readOnly.of(readOnly))})},[readOnly]);
  const run=(command:(view:EditorView)=>boolean)=>{const view=editor.current;if(view){command(view);view.focus()}};
  const clipboard=async(kind:'copy'|'cut'|'paste')=>{
    const view=editor.current;if(!view)return;setMessage('');
    try{const done=await ({copy:copyText,cut:cutText,paste:pasteText}[kind])(view);if(editor.current===view){setMessage(done?{copy:'已复制',cut:'已剪切',paste:'已粘贴'}[kind]:'请先选择文本或检查剪贴板');view.focus()}}
    catch(e){if(editor.current===view)setMessage((e instanceof Error?e.message:'剪贴板不可用')+'；也可以在编辑区使用 Ctrl+C/X/V')}
  };
  const tool=(label:string,icon:React.ReactNode,action:()=>void,disabled=false,title=label)=><button type="button" className="secondary" title={title} disabled={disabled} onMouseDown={e=>e.preventDefault()} onClick={action}>{icon}{label}</button>;
  return <div className="text-editor">
    <div className="text-editor-tools" role="toolbar" aria-label="文本编辑工具">
      {tool('撤销',<Undo2 size={14}/>,()=>run(undo),readOnly||!info.undo,'撤销 · Ctrl+Z')}{tool('重做',<Redo2 size={14}/>,()=>run(redo),readOnly||!info.redo,'重做 · Ctrl+Y / Ctrl+Shift+Z')}
      {tool('复制',<Copy size={14}/>,()=>void clipboard('copy'),!info.selected,'复制 · Ctrl+C')}{tool('剪切',<Scissors size={14}/>,()=>void clipboard('cut'),readOnly||!info.selected,'剪切 · Ctrl+X')}{tool('粘贴',<ClipboardPaste size={14}/>,()=>void clipboard('paste'),readOnly,'粘贴 · Ctrl+V')}{tool('全选',<TextSelect size={14}/>,()=>run(selectAll),false,'全选 · Ctrl+A')}
      {tool('查找',<Search size={14}/>,()=>{const view=editor.current;if(view)openSearchPanel(view)},false,'查找当前文件 · Ctrl+F')}{tool('替换',<Replace size={14}/>,()=>{const view=editor.current;if(view)openReplace(view)},readOnly,'查找替换 · Ctrl+H')}
      {tool('跳转行',<ListOrdered size={14}/>,()=>{const view=editor.current;if(view)gotoLine(view)},false,'跳转到行 · Ctrl+Alt+G')}
      <button type="button" className="secondary" aria-pressed={wrap} onMouseDown={e=>e.preventDefault()} onClick={()=>{const next=!wrap;setWrap(next);editor.current?.dispatch({effects:wrapping.current.reconfigure(next?EditorView.lineWrapping:[])})}}><WrapText size={14}/>自动换行</button>
    </div>
    {message&&<p className="file-inline" role="status">{message}</p>}
    <div className="text-editor-content" ref={element}/>
    <div className="text-editor-status"><span>行 {info.line}，列 {info.column}{info.selected?' · 已选择 '+info.selected+' 个字符':''}</span><span aria-live="polite">{info.matches}</span></div>
  </div>;
}
