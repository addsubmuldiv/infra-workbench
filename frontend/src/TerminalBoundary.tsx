import React from 'react';
import './terminalBoundary.css';

export class TerminalBoundary extends React.Component<{children:React.ReactNode;close:()=>void},{failed:boolean}>{
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true}}
  render(){
    if(!this.state.failed)return this.props.children;
    return <section className="terminal-load-error" role="alert" aria-label="终端打开失败">
      <h2>终端暂时无法打开</h2>
      <p>页面可能已更新，或终端组件加载失败。请刷新页面后重试。</p>
      <p>刷新会断开当前页面的终端连接，请先确认其他窗口中没有未保存的编辑。</p>
      <div><button className="secondary" onClick={()=>{this.setState({failed:false});this.props.close()}}>关闭提示</button><button className="primary" onClick={()=>window.location.reload()}>刷新页面</button></div>
    </section>;
  }
}
