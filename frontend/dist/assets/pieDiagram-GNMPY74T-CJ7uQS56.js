import{p as at}from"./chunk-JWPE2WC7-OnHxBWXS.js";import{a9 as b,ac as G,bb as rt,g as nt,s as it,a as ot,b as st,t as lt,q as ct,_ as g,l as B,c as ut,M as dt,P as gt,U as pt,d as ht,z as ft,N as mt}from"./mermaid.core-almhKv4x.js";import{p as vt}from"./cynefin-EF2NZ3EQ-BCifPtoo.js";import{d as Z}from"./arc-DIwjiLFg.js";import{o as xt}from"./ordinal-Cboi1Yqb.js";import"./index-f5Kk9mWx.js";import"./AssistantWindow-DI0AdnFz.js";import"./skills-lxi43KaD.js";import"./AppConfirm-CqK1mP0I.js";import"./index-D72TmlV-.js";import"./windowLayers-C9W3NSUA.js";import"./minus-C6paJ6cx.js";import"./init-Gi6I4Gst.js";function yt(t,n){return n<t?-1:n>t?1:n>=t?0:NaN}function St(t){return t}function wt(){var t=St,n=yt,S=null,T=b(0),l=b(G),p=b(0);function i(e){var r,s=(e=rt(e)).length,h,w,D=0,f=new Array(s),o=new Array(s),A=+T.apply(this,arguments),M=Math.min(G,Math.max(-G,l.apply(this,arguments)-A)),k,L=Math.min(Math.abs(M)/s,p.apply(this,arguments)),u=L*(M<0?-1:1),C;for(r=0;r<s;++r)(C=o[f[r]=r]=+t(e[r],r,e))>0&&(D+=C);for(n!=null?f.sort(function(E,m){return n(o[E],o[m])}):S!=null&&f.sort(function(E,m){return S(e[E],e[m])}),r=0,w=D?(M-s*u)/D:0;r<s;++r,A=k)h=f[r],C=o[h],k=A+(C>0?C*w:0)+u,o[h]={data:e[h],index:r,value:C,startAngle:A,endAngle:k,padAngle:L};return o}return i.value=function(e){return arguments.length?(t=typeof e=="function"?e:b(+e),i):t},i.sortValues=function(e){return arguments.length?(n=e,S=null,i):n},i.sort=function(e){return arguments.length?(S=e,n=null,i):S},i.startAngle=function(e){return arguments.length?(T=typeof e=="function"?e:b(+e),i):T},i.endAngle=function(e){return arguments.length?(l=typeof e=="function"?e:b(+e),i):l},i.padAngle=function(e){return arguments.length?(p=typeof e=="function"?e:b(+e),i):p},i}var At=mt.pie,I={sections:new Map,showData:!1},_=I.sections,U=I.showData,Ct=structuredClone(At),$t=g(()=>structuredClone(Ct),"getConfig"),Dt=g(()=>{_=new Map,U=I.showData,ft()},"clear"),bt=g(({label:t,value:n})=>{if(n<0)throw new Error(`"${t}" has invalid value: ${n}. Negative values are not allowed in pie charts. All slice values must be >= 0.`);_.has(t)||(_.set(t,n),B.debug(`added new section: ${t}, with value: ${n}`))},"addSection"),Tt=g(()=>_,"getSections"),kt=g(t=>{U=t},"setShowData"),zt=g(()=>U,"getShowData"),J={getConfig:$t,clear:Dt,setDiagramTitle:ct,getDiagramTitle:lt,setAccTitle:st,getAccTitle:ot,setAccDescription:it,getAccDescription:nt,addSection:bt,getSections:Tt,setShowData:kt,getShowData:zt},Mt=g((t,n)=>{at(t,n),n.setShowData(t.showData),t.sections.map(n.addSection)},"populateDb"),Et={parse:g(async t=>{const n=await vt("pie",t);B.debug(n),Mt(n,J)},"parse")},Rt=g(t=>`
  .pieCircle{
    stroke: ${t.pieStrokeColor};
    stroke-width : ${t.pieStrokeWidth};
    opacity : ${t.pieOpacity};
  }
  .pieCircle.highlighted{
    scale: 1.05;
    opacity: 1;
  }
  .pieCircle.highlightedOnHover:hover{
    transition-duration: 250ms;
    scale: 1.05;
    opacity: 1;
  }
  .pieOuterCircle{
    stroke: ${t.pieOuterStrokeColor};
    stroke-width: ${t.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${t.pieTitleTextSize};
    fill: ${t.pieTitleTextColor};
    font-family: ${t.fontFamily};
  }
  .slice {
    font-family: ${t.fontFamily};
    fill: ${t.pieSectionTextColor};
    font-size:${t.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${t.pieLegendTextColor};
    font-family: ${t.fontFamily};
    font-size: ${t.pieLegendTextSize};
  }
`,"getStyles"),Lt=Rt,Nt=g(t=>{const n=[...t.values()].reduce((l,p)=>l+p,0),S=[...t.entries()].map(([l,p])=>({label:l,value:p})).filter(l=>l.value/n*100>=1);return wt().value(l=>l.value).sort(null)(S)},"createPieArcs"),Pt=g((t,n,S,T)=>{B.debug(`rendering pie chart
`+t);const l=T.db,p=ut(),i=dt(l.getConfig(),p.pie),e=40,r=18,s=4,h=450,w=h,D=gt(n),f=D.append("g");f.attr("transform","translate("+w/2+","+h/2+")");const{themeVariables:o}=p;let[A]=pt(o.pieOuterStrokeWidth);A??(A=2);const M=i.legendPosition,k=i.textPosition,L=i.donutHole>0&&i.donutHole<=.9?i.donutHole:0,u=Math.min(w,h)/2-e,C=Z().innerRadius(L*u).outerRadius(u),E=Z().innerRadius(u*k).outerRadius(u*k),m=f.append("g");m.append("circle").attr("cx",0).attr("cy",0).attr("r",u+A/2).attr("class","pieOuterCircle");const N=l.getSections(),K=Nt(N),Q=[o.pie1,o.pie2,o.pie3,o.pie4,o.pie5,o.pie6,o.pie7,o.pie8,o.pie9,o.pie10,o.pie11,o.pie12];let F=0;N.forEach(a=>{F+=a});const V=K.filter(a=>(a.data.value/F*100).toFixed(0)!=="0"),H=xt(Q).domain([...N.keys()]);m.selectAll("mySlices").data(V).enter().append("path").attr("d",C).attr("fill",a=>H(a.data.label)).attr("class",a=>{let c="pieCircle";return i.highlightSlice==="hover"?c+=" highlightedOnHover":i.highlightSlice===a.data.label&&(c+=" highlighted"),c}),m.selectAll("mySlices").data(V).enter().append("text").text(a=>(a.data.value/F*100).toFixed(0)+"%").attr("transform",a=>"translate("+E.centroid(a)+")").style("text-anchor","middle").attr("class","slice");const Y=f.append("text").text(l.getDiagramTitle()).attr("x",0).attr("y",-400/2).attr("class","pieTitleText"),R=[...N.entries()].map(([a,c])=>({label:a,value:c})),$=f.selectAll(".legend").data(R).enter().append("g").attr("class","legend");$.append("rect").attr("width",r).attr("height",r).style("fill",a=>H(a.label)).style("stroke",a=>H(a.label)),$.append("text").attr("x",r+s).attr("y",r-s).text(a=>l.getShowData()?`${a.label} [${a.value}]`:a.label);const z=Math.max(...$.selectAll("text").nodes().map(a=>a?.getBoundingClientRect().width??0));let P=h,O=w+e;const d=r+s,W=R.length*d;switch(M){case"center":$.attr("transform",(a,c)=>{const v=d*R.length/2,x=-z/2-(r+s),y=c*d-v;return"translate("+x+","+y+")"});break;case"top":P+=W,$.attr("transform",(a,c)=>{const v=u,x=-z/2-(r+s),y=c*d-v;return`translate(${x}, ${y})`}),m.attr("transform",()=>`translate(0, ${W+d})`);break;case"bottom":P+=W,$.attr("transform",(a,c)=>{const v=-u-d,x=-z/2-(r+s),y=c*d-v;return"translate("+x+","+y+")"});break;case"left":O+=r+s+z,$.attr("transform",(a,c)=>{const v=d*R.length/2,x=-u-(r+s),y=c*d-v;return"translate("+x+","+y+")"}),m.attr("transform",()=>`translate(${z+r+s}, 0)`);break;default:O+=r+s+z,$.attr("transform",(a,c)=>{const v=d*R.length/2,x=12*r,y=c*d-v;return"translate("+x+","+y+")"});break}const j=Y.node()?.getBoundingClientRect().width??0,tt=w/2-j/2,et=w/2+j/2,q=Math.min(0,tt),X=Math.max(O,et)-q;D.attr("viewBox",`${q} 0 ${X} ${P}`),ht(D,P,X,i.useMaxWidth)},"draw"),_t={draw:Pt},Kt={parser:Et,db:J,renderer:_t,styles:Lt};export{Kt as diagram};
