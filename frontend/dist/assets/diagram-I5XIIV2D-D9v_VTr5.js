import{p as z}from"./chunk-JWPE2WC7-DRVsjra9.js";import{_ as f,M as B,P,d as E,l as $,b as F,a as A,q as W,t as _,g as N,s as M,K as L,N as Y,z as I}from"./mermaid.core-DzIl3S4o.js";import{p as K}from"./cynefin-EF2NZ3EQ-BkZnj1C_.js";import"./index-Cz2t4xD2.js";import"./AssistantWindow-CU6cmnyu.js";import"./skills-2nzihu6J.js";import"./AppConfirm-BjT_fHmr.js";import"./index-BreGf7pF.js";import"./settings-2-2YDZYtyK.js";import"./windowLayers-C9W3NSUA.js";import"./minus-ClTbSO5T.js";var O=Y.packet,u,C=(u=class{constructor(){this.packet=[],this.setAccTitle=F,this.getAccTitle=A,this.setDiagramTitle=W,this.getDiagramTitle=_,this.getAccDescription=N,this.setAccDescription=M}getConfig(){const t=B({...O,...L().packet});return t.showBits&&(t.paddingY+=10),t}getPacket(){return this.packet}pushWord(t){t.length>0&&this.packet.push(t)}clear(){I(),this.packet=[]}},f(u,"PacketDB"),u),j=1e4,q=f((e,t)=>{z(e,t);let r=-1,i=[],s=1;const{bitsPerRow:l}=t.getConfig();for(let{start:a,end:o,bits:c,label:g}of e.blocks){if(a!==void 0&&o!==void 0&&o<a)throw new Error(`Packet block ${a} - ${o} is invalid. End must be greater than start.`);if(a??(a=r+1),a!==r+1)throw new Error(`Packet block ${a} - ${o??a} is not contiguous. It should start from ${r+1}.`);if(c===0)throw new Error(`Packet block ${a} is invalid. Cannot have a zero bit field.`);for(o??(o=a+(c??1)-1),c??(c=o-a+1),r=o,$.debug(`Packet block ${a} - ${r} with label ${g}`);i.length<=l+1&&t.getPacket().length<j;){const[d,p]=G({start:a,end:o,bits:c,label:g},s,l);if(i.push(d),d.end+1===s*l&&(t.pushWord(i),i=[],s++),!p)break;({start:a,end:o,bits:c,label:g}=p)}}t.pushWord(i)},"populate"),G=f((e,t,r)=>{if(e.start===void 0)throw new Error("start should have been set during first phase");if(e.end===void 0)throw new Error("end should have been set during first phase");if(e.start>e.end)throw new Error(`Block start ${e.start} is greater than block end ${e.end}.`);if(e.end+1<=t*r)return[e,void 0];const i=t*r-1,s=t*r;return[{start:e.start,end:i,label:e.label,bits:i-e.start},{start:s,end:e.end,label:e.label,bits:e.end-s}]},"getNextFittingBlock"),S={parser:{yy:void 0},parse:f(async e=>{const t=await K("packet",e),r=S.parser?.yy;if(!(r instanceof C))throw new Error("parser.parser?.yy was not a PacketDB. This is due to a bug within Mermaid, please report this issue at https://github.com/mermaid-js/mermaid/issues.");$.debug(t),q(t,r)},"parse")},H=f((e,t,r,i)=>{const s=i.db,l=s.getConfig(),{rowHeight:a,paddingY:o,bitWidth:c,bitsPerRow:g}=l,d=s.getPacket(),p=s.getDiagramTitle(),b=a+o,n=b*(d.length+1)-(p?0:a),h=c*g+2,k=P(t);k.attr("viewBox",`0 0 ${h} ${n}`),E(k,n,h,l.useMaxWidth);for(const[x,m]of d.entries())U(k,m,x,l);k.append("text").text(p).attr("x",h/2).attr("y",n-b/2).attr("dominant-baseline","middle").attr("text-anchor","middle").attr("class","packetTitle")},"draw"),U=f((e,t,r,{rowHeight:i,paddingX:s,paddingY:l,bitWidth:a,bitsPerRow:o,showBits:c,bitOrder:g})=>{const d=e.append("g"),p=r*(i+l)+l,b=g==="descending";for(const n of t){const h=n.end-n.start+1,k=n.start%o,m=(b?o-k-h:k)*a+1,w=h*a-s;if(d.append("rect").attr("x",m).attr("y",p).attr("width",w).attr("height",i).attr("class","packetBlock"),d.append("text").attr("x",m+w/2).attr("y",p+i/2).attr("class","packetLabel").attr("dominant-baseline","middle").attr("text-anchor","middle").text(n.label),!c)continue;const[D,T]=b?[n.end,n.start]:[n.start,n.end],v=h===1,y=p-2;d.append("text").attr("x",m+(v?w/2:0)).attr("y",y).attr("class","packetByte start").attr("dominant-baseline","auto").attr("text-anchor",v?"middle":"start").text(D),v||d.append("text").attr("x",m+w).attr("y",y).attr("class","packetByte end").attr("dominant-baseline","auto").attr("text-anchor","end").text(T)}},"drawWord"),X={draw:H},J={byteFontSize:"10px",startByteColor:"black",endByteColor:"black",labelColor:"black",labelFontSize:"12px",titleColor:"black",titleFontSize:"14px",blockStrokeColor:"black",blockStrokeWidth:"1",blockFillColor:"#efefef"},Q=f(({packet:e}={})=>{const t=B(J,e);return`
	.packetByte {
		font-size: ${t.byteFontSize};
	}
	.packetByte.start {
		fill: ${t.startByteColor};
	}
	.packetByte.end {
		fill: ${t.endByteColor};
	}
	.packetLabel {
		fill: ${t.labelColor};
		font-size: ${t.labelFontSize};
	}
	.packetTitle {
		fill: ${t.titleColor};
		font-size: ${t.titleFontSize};
	}
	.packetBlock {
		stroke: ${t.blockStrokeColor};
		stroke-width: ${t.blockStrokeWidth};
		fill: ${t.blockFillColor};
	}
	`},"styles"),lt={parser:S,get db(){return new C},renderer:X,styles:Q};export{lt as diagram};
