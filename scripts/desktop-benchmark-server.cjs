const http=require('node:http');
const net=require('node:net');
const fs=require('node:fs/promises');
const path=require('node:path');
const {performance}=require('node:perf_hooks');

const browserScript=String.raw`(()=>{
  window.__benchCommits=0;
  if(window.__benchUI&&!window.__REACT_DEVTOOLS_GLOBAL_HOOK__)window.__REACT_DEVTOOLS_GLOBAL_HOOK__={supportsFiber:true,inject:()=>1,onCommitFiberRoot(){window.__benchCommits++},onCommitFiberUnmount(){}};
  let sent=false;
  const sendReady=()=>{
    if(sent||document.readyState==='loading'||document.fonts.status!=='loaded'||!document.querySelector('[aria-label="只看机器 bench-01"]'))return;
    sent=true;observer.disconnect();
    requestAnimationFrame(()=>requestAnimationFrame(()=>fetch('/__bench/ready',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({at:Date.now(),navigationMs:performance.now(),width:innerWidth,height:innerHeight,dpr:devicePixelRatio,visibility:document.visibilityState,ua:navigator.userAgent})})));
  };
  const observer=new MutationObserver(sendReady);observer.observe(document,{childList:true,subtree:true});
  addEventListener('DOMContentLoaded',()=>document.fonts.ready.then(sendReady));
  window.__bench={start(){
    const metrics={frames:[],longTasks:[],eventLoopLag:[],tabLatency:[],tabTimeouts:0};
    let last=performance.now(),active=true,frameId;
    const frame=now=>{if(!active)return;metrics.frames.push(now-last);last=now;frameId=requestAnimationFrame(frame)};
    frameId=requestAnimationFrame(frame);
    const observer=new PerformanceObserver(list=>{for(const task of list.getEntries())metrics.longTasks.push(task.duration)});observer.observe({type:'longtask'});
    let timerLast=performance.now();const timer=setInterval(()=>{const now=performance.now();metrics.eventLoopLag.push(Math.max(0,now-timerLast-100));timerLast=now},100);
    const clicked=event=>{
      const tab=event.target.closest('[role="tab"]');if(!tab||tab.getAttribute('aria-selected')==='true')return;
      const begin=performance.now();
      const selected=()=>{if(!active)return;if(tab.getAttribute('aria-selected')==='true')requestAnimationFrame(()=>requestAnimationFrame(()=>metrics.tabLatency.push(performance.now()-begin)));else if(performance.now()-begin<2000)requestAnimationFrame(selected);else metrics.tabTimeouts++};
      requestAnimationFrame(selected);
    };document.addEventListener('pointerdown',clicked,true);
    this.stop=()=>{active=false;cancelAnimationFrame(frameId);clearInterval(timer);observer.disconnect();document.removeEventListener('pointerdown',clicked,true);metrics.renderers=Array.from(document.querySelectorAll('.terminal-screen'),el=>({active:el.classList.contains('active'),renderer:el.dataset.renderer||'dom',canvases:el.querySelectorAll('canvas').length}));return metrics};
  }};
})()`;

module.exports=async function createFixture(snapshot,WebSocketServer,options={}){
  const GiB=1024**3;
  const hosts=Array.from({length:48},(_,i)=>({id:'bench-'+String(i+1).padStart(2,'0'),target:'bench-'+String(i+1).padStart(2,'0'),user:'demo',port:22,manual:true,auth:'key',snapshot:{status:'online',fresh:true,collected_at:1700000000,system:{cpu_percent:12,cpu_cores:64,memory:{memory_total:256*GiB,memory_used:32*GiB,memory_available:224*GiB}},devices:Array.from({length:8},(_,j)=>({id:String(j),kind:'GPU',name:'Demo accelerator',memory_total:80*GiB,memory_used:8*GiB,memory_free:72*GiB,utilization:10,temperature:40,health:'OK',processes:[],processes_known:true}))}}));
  let run=null,phase=null,ticker=null,uploadBytes=0;
  const connections=new Map();
  const line='\x1b[32m[train rank=00]\x1b[0m step=123456 loss=0.234500 lr=1.0e-5 tokens_per_second=12345\r\n';
  const payload=line.repeat(32),chunkBytes=Buffer.byteLength(payload);
  const json=(res,value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value))};
  const server=http.createServer(async(req,res)=>{
    try{
      const url=new URL(req.url,'http://127.0.0.1:8765');
      if(url.hostname!=='127.0.0.1'||url.port!=='8765')return json(res,{blocked:true},403);
      if(url.pathname==='/__bench/init.js'){res.writeHead(200,{'Content-Type':'text/javascript','Cache-Control':'no-store'});return res.end((options.ui?'window.__benchUI=true;':'')+(options.renderer?'history.replaceState(null,"","/?terminal-renderer='+options.renderer+'");':'')+browserScript)}
      if(url.pathname==='/__bench/ready'){
        let body='';for await(const part of req)body+=part;
        const info=JSON.parse(body);if(run&&!run.ready){run.ready={...info,observedAt:performance.now()};run.resolveReady(run.ready)}
        return json(res,{ok:true});
      }
      if(url.pathname==='/api/state')return json(res,{hosts,rules:[],reservations:[],events:[],server_time:Date.now()/1000});
      if(url.pathname==='/api/files/uploads/desktop-upload'&&req.method==='PUT'){
        for await(const part of req)uploadBytes+=part.length;
        return json(res,{id:'desktop-upload',status:'done',path:'/demo/upload-check.txt'});
      }
      if(url.pathname==='/api/logs/configs')return json(res,[]);
      if(url.pathname==='/api/mcp-info')return json(res,{path:'/mcp',transport:'streamable-http',tools:[]});
      if(url.pathname==='/api/settings/agent')return json(res,{active_id:'legacy',default_id:'legacy',profiles:[{id:'legacy',name:'Demo',model:''}],base_url:'',protocol:'auto',model:'',timeout_seconds:45,can_remember:false,has_api_key:false,api_key_saved:false,credential_error:'',last_test:null});
      if(url.pathname==='/api/workspace-state')return json(res,{revision:0,values:{}});
      if(url.pathname==='/api/settings/launch')return json(res,{mode:'browser',desktop_available:true,show_floating:false,floating_available:false});
      if(url.pathname==='/api/automations')return json(res,{items:[],runs:[],tools:{}});
      if(url.pathname==='/api/settings/mail')return json(res,{enabled:false,host:'',port:465,security:'ssl',username:'',sender:'',recipients:[],can_remember:false,has_password:false,password_saved:false,credential_error:'',last_test:null,last_delivery:null,reservation_available:false});
      if(url.pathname.endsWith('/terminal-ticket'))return json(res,{ticket:'benchmark-ticket',workspace:false});
      if(url.pathname.endsWith('/terminal-workspace'))return json(res,{sessions:[]});
      if(url.pathname.startsWith('/api/'))return json(res,{items:[],sessions:[]});
      const name=url.pathname==='/'?'index.html':decodeURIComponent(url.pathname).replace(/^\/+/, '');
      const target=path.resolve(snapshot,name);
      if(target!==snapshot&&!target.startsWith(snapshot+path.sep))return json(res,{blocked:true},403);
      let content=await fs.readFile(target);
      const type={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'}[path.extname(target)]||'application/octet-stream';
      if(name==='index.html')content=Buffer.from(content.toString().replace('<head>','<head><script src="/__bench/init.js"></script>'));
      res.writeHead(200,{'Content-Type':type,'Cache-Control':name==='index.html'?'no-store':'public,max-age=31536000,immutable'});res.end(content);
    }catch(error){json(res,{error:error.message},404)}
  });
  const websocket=new WebSocketServer({noServer:true});
  server.on('connection',socket=>socket.on('error',()=>{}));
  server.on('clientError',(_,socket)=>socket.destroy());
  server.on('upgrade',(req,socket,head)=>{
    const url=new URL(req.url,'http://127.0.0.1:8765');
    if(!url.pathname.startsWith('/api/terminal/'))return socket.destroy();
    websocket.handleUpgrade(req,socket,head,ws=>{
      const id=url.pathname.split('/').at(-1),connection={id,ws,ready:false,queue:[],sent:0};
      connections.set(id,connection);
      ws.on('error',()=>{});
      ws.on('message',raw=>{
        const message=JSON.parse(raw.toString());
        if(message.type==='resize'&&!connection.ready){connection.ready=true;ws.send(JSON.stringify({type:'ready'}))}
        if(message.type==='ack'){
          const item=connection.queue.shift();if(item){item.phase.ackBytes+=item.bytes;item.phase.acks++;item.phase.latencies.push(performance.now()-item.at)}
        }
      });
      ws.on('close',()=>{if(phase?.active&&connection.queue.length)phase.prematureClosures++;connections.delete(id)});
    });
  });
  server.on('connect',(req,socket,head)=>{
    if(req.url!=='127.0.0.1:8765')return socket.end('HTTP/1.1 403 Forbidden\r\n\r\n');
    const upstream=net.connect(server.address().port,'127.0.0.1',()=>{socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');if(head.length)upstream.write(head);upstream.pipe(socket);socket.pipe(upstream)});
    upstream.on('error',()=>socket.destroy());socket.on('error',()=>upstream.destroy());socket.on('close',()=>upstream.destroy());
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  return {
    port:server.address().port,connections,inventory:hosts,get uploadBytes(){return uploadBytes},
    beginRun(label){let resolveReady;const readyPromise=new Promise(resolve=>resolveReady=resolve);run={label,readyPromise,resolveReady};return run},
    startPhase(count,rate){
      phase={count,rate,chunkBytes,begin:performance.now(),active:true,sentBytes:0,ackBytes:0,acks:0,latencies:[],maxInFlight:0,creditLimitedTicks:0,prematureClosures:0,tickLag:[]};
      const own=phase;for(const connection of connections.values())connection.sent=0;
      let last=performance.now();ticker=setInterval(()=>{
        const now=performance.now();own.tickLag.push(Math.max(0,now-last-20));last=now;
        const due=Math.floor((now-own.begin)/1000*rate/chunkBytes);
        for(let i=1;i<=count;i++){
          const connection=connections.get('bench-'+String(i).padStart(2,'0'));if(!connection?.ready)continue;
          if(connection.queue.length>=8&&connection.sent<due)own.creditLimitedTicks++;
          while(connection.sent<due&&connection.queue.length<8&&connection.ws.readyState===1){
            connection.queue.push({at:performance.now(),bytes:chunkBytes,phase:own});connection.sent++;own.sentBytes+=chunkBytes;
            connection.ws.send(JSON.stringify({type:'output',data:payload}));own.maxInFlight=Math.max(own.maxInFlight,connection.queue.length);
          }
        }
      },20);return phase;
    },
    async stopPhase(){const own=phase;own.active=false;clearInterval(ticker);own.elapsedSeconds=(performance.now()-own.begin)/1000;
      const end=performance.now()+5000;while([...connections.values()].some(c=>c.queue.length)&&performance.now()<end)await new Promise(r=>setTimeout(r,20));
      own.pendingMessages=[...connections.values()].reduce((n,c)=>n+c.queue.length,0);return own;
    },
    async close(){clearInterval(ticker);for(const connection of connections.values())connection.ws.close();websocket.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
  };
};
