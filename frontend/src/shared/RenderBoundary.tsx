import React from 'react';
import {t,useLocale} from './i18n';
import './renderBoundary.css';

class RenderBoundary extends React.Component<{children:React.ReactNode;fallback:React.ReactNode},{failed:boolean}>{
  state={failed:false};

  static getDerivedStateFromError(){return {failed:true}}

  render(){return this.state.failed?this.props.fallback:this.props.children}
}

export function RenderFailure({title,close,floating=false}:{title:string;close?:()=>void;floating?:boolean}){
  useLocale();
  return <section className={'render-failure'+(floating?' floating':'')} role="alert">
    <h2>{title}</h2>
    <p>{t('刷新页面后可重新加载。刷新会断开当前页面的终端连接，请先保存未完成的编辑。','Reload the page to try again. Reloading disconnects terminals on this page. Save unfinished edits first.')}</p>
    <div>
      {close&&<button type="button" className="secondary" onClick={close}>{t('关闭提示','Dismiss')}</button>}
      <button type="button" className="primary" onClick={()=>window.location.reload()}>{t('刷新页面','Reload page')}</button>
    </div>
  </section>;
}

export {RenderBoundary};
