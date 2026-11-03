import {t,useLocale} from './i18n';
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
  const locale=useLocale();
  const language=useRef(new Compartment());
  const element=useRef<HTMLDivElement>(null),editor=useRef<EditorView|null>(null),onChangeRef=useRef(onChange);onChangeRef.current=onChange;
  const editable=useRef(new Compartment()),wrapping=useRef(new Compartment());
  const [wrap,setWrap]=useState(false),[message,setMessage]=useState('');
  const [info,setInfo]=useState({line:1,column:1,selected:0,undo:false,redo:false,matches:''});
  useEffect(()=>{
    let alive=true;
    const updateInfo=(state:EditorState,matches?:string)=>{const selection=state.selection.main,line=state.doc.lineAt(selection.head);
      setInfo(old=>({line:line.number,column:selection.head-line.from+1,selected:state.selection.ranges.reduce((sum,r)=>sum+r.to-r.from,0),undo:undoDepth(state)>0,redo:redoDepth(state)>0,matches:matches??old.matches}))};
    const view=new EditorView({parent:element.current!,state:EditorState.create({doc:value,extensions:[
      lineNumbers(),drawSelection(),highlightActiveLine(),history(),highlightSelectionMatches(),search({top:true}),language.current.of(EditorState.phrases.of(locale==='zh'?phrases:{})),editorTheme,
      editable.current.of(EditorState.readOnly.of(readOnly)),wrapping.current.of([]),
      EditorView.contentAttributes.of(view=>({'aria-label':t("文件文本内容","File text content"),spellcheck:'false'})),
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
  useEffect(()=>{const view=editor.current;if(view){view.dispatch({effects:language.current.reconfigure(EditorState.phrases.of(locale==='zh'?phrases:{}))});setInfo(old=>({...old,matches:searchMatchCount(view.state)}))}},[locale]);
  const run=(command:(view:EditorView)=>boolean)=>{const view=editor.current;if(view){command(view);view.focus()}};
  const clipboard=async(kind:'copy'|'cut'|'paste')=>{
    const view=editor.current;if(!view)return;setMessage('');
    try{const done=await ({copy:copyText,cut:cutText,paste:pasteText}[kind])(view);if(editor.current===view){setMessage(done?{copy:t("已复制","Copied"),cut:t("已剪切","Cut"),paste:t("已粘贴","Pasted")}[kind]:t("请先选择文本或检查剪贴板","Select text or check clipboard access first"));view.focus()}}
    catch(e){if(editor.current===view)setMessage((e instanceof Error?e.message:t("剪贴板不可用","Clipboard unavailable"))+t("；也可以在编辑区使用 Ctrl/⌘+C/X/V","; you can also use Ctrl/⌘+C/X/V in the editor"))}
  };
  const tool=(label:string,icon:React.ReactNode,action:()=>void,disabled=false,title=label)=><button type="button" className="secondary" title={title} disabled={disabled} onMouseDown={e=>e.preventDefault()} onClick={action}>{icon}{label}</button>;
  return <div className="text-editor">
    <div className="text-editor-tools" role="toolbar" aria-label={t("文本编辑工具","Text editing tools")}>
      {tool(t("撤销","Undo"),<Undo2 size={14}/>,()=>run(undo),readOnly||!info.undo,t("撤销 · Ctrl/⌘+Z","Undo · Ctrl/⌘+Z"))}{tool(t("重做","Redo"),<Redo2 size={14}/>,()=>run(redo),readOnly||!info.redo,t("重做 · Ctrl/⌘+Y / Ctrl/⌘+Shift+Z","Redo · Ctrl/⌘+Y / Ctrl/⌘+Shift+Z"))}
      {tool(t("复制","Copy"),<Copy size={14}/>,()=>void clipboard('copy'),!info.selected,t("复制 · Ctrl/⌘+C","Copy · Ctrl/⌘+C"))}{tool(t("剪切","Cut"),<Scissors size={14}/>,()=>void clipboard('cut'),readOnly||!info.selected,t("剪切 · Ctrl/⌘+X","Cut · Ctrl/⌘+X"))}{tool(t("粘贴","Paste"),<ClipboardPaste size={14}/>,()=>void clipboard('paste'),readOnly,t("粘贴 · Ctrl/⌘+V","Paste · Ctrl/⌘+V"))}{tool(t("全选","Select all"),<TextSelect size={14}/>,()=>run(selectAll),false,t("全选 · Ctrl/⌘+A","Select all · Ctrl/⌘+A"))}
      {tool(t("查找","Find"),<Search size={14}/>,()=>{const view=editor.current;if(view)openSearchPanel(view)},false,t("查找当前文件 · Ctrl/⌘+F","Find in file · Ctrl/⌘+F"))}{tool(t("替换","Replace"),<Replace size={14}/>,()=>{const view=editor.current;if(view)openReplace(view)},readOnly,t("查找替换 · Ctrl/⌘+H","Find and replace · Ctrl/⌘+H"))}
      {tool(t("跳转行","Go to line"),<ListOrdered size={14}/>,()=>{const view=editor.current;if(view)gotoLine(view)},false,t("跳转到行 · Ctrl/⌘+Alt+G","Go to line · Ctrl/⌘+Alt+G"))}
      <button type="button" className="secondary" aria-pressed={wrap} onMouseDown={e=>e.preventDefault()} onClick={()=>{const next=!wrap;setWrap(next);editor.current?.dispatch({effects:wrapping.current.reconfigure(next?EditorView.lineWrapping:[])})}}><WrapText size={14}/>{t("自动换行","Word wrap")}</button>
    </div>
    {message&&<p className="file-inline" role="status">{message}</p>}
    <div className="text-editor-content" ref={element}/>
    <div className="text-editor-status"><span>{t("行","Line ")}{info.line}{t("，列",", column ")}{info.column}{info.selected?t("· 已选择","· selected ")+info.selected+t("个字符"," characters"):''}</span><span aria-live="polite">{info.matches}</span></div>
  </div>;
}
