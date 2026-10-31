// Run against the task-owned desktop WebView through Playwright CDP.
// All API/terminal traffic is intercepted; no remote machine is contacted.
module.exports=async (page,fixture) => {
  const result={saved:null,uploadBytes:0,terminalInput:'',terminalAcks:0,stage:'setup'};
  page.setDefaultTimeout(5000);
  page.desktopFlowResult=result;
  const uploadStart=fixture?.uploadBytes||0;
  const host={id:'desktop-demo',target:'desktop-demo',user:'demo',port:22,manual:true,auth:'key',
    snapshot:{status:'online',fresh:true,collected_at:1700000000,devices:[]}};
  let content='Desktop editor check\n';
  await page.unroute('**/api/**');
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    let data;
    if(path==='/api/state')data={hosts:[host],rules:[],reservations:[],events:[],server_time:1700000000};
    else if(path==='/api/files/capabilities')data={editing:true,upload:true,search:true,terminal_cwd:true,transfer_progress:true,folder_download:true,folder_upload:true};
    else if(path==='/api/files/browse')data={path:'/demo',parent:'/',entries:[{name:'check.txt',path:'/demo/check.txt',kind:'file',symlink:false,size:content.length,modified:1700000000,accessible:true}],total:1,next_offset:null};
    else if(path==='/api/files/operation'){
      const command=request.postDataJSON();
      if(command.op==='save'){content=command.content;result.saved=content;}
      data={path:'/demo/check.txt',content,revision:'demo-revision',bytes:content.length,newline:'LF'};
    }
    else if(path==='/api/files/uploads')data={id:'desktop-upload',status:'receiving'};
    else if(path==='/api/files/uploads/desktop-upload'){
      if(request.method()==='PUT'&&fixture)return route.continue();
      if(request.method()==='PUT')result.uploadBytes=request.postDataBuffer()?.length||0;
      data={id:'desktop-upload',status:'done',path:'/demo/upload-check.txt'};
    }
    else if(path.endsWith('/terminal-ticket'))data={ticket:'demo-ticket',workspace:false};
    else if(path.endsWith('/terminal-workspace'))data={sessions:[]};
    else return route.fulfill({status:404,json:{detail:'No synthetic route: '+path}});
    return route.fulfill({json:data});
  });
  await page.routeWebSocket('**/api/terminal/desktop-demo',socket=>{
    let ready=false;
    socket.onMessage(raw=>{
      const message=JSON.parse(String(raw));
      if(message.type==='resize'&&!ready){ready=true;socket.send(JSON.stringify({type:'ready'}));socket.send(JSON.stringify({type:'output',data:'Desktop terminal ready\r\n$ '}));}
      if(message.type==='ack')result.terminalAcks++;
      if(message.type==='input'){result.terminalInput+=message.data;socket.send(JSON.stringify({type:'output',data:message.data}));}
    });
  });
  await page.reload();
  result.stage='open file browser';
  await page.getByRole('button',{name:'浏览 desktop-demo 文件',exact:true}).click();
  await page.getByRole('button',{name:'文件 /demo/check.txt',exact:true}).dblclick();
  const editor=page.locator('.cm-content');
  result.stage='save editor';
  await editor.fill('桌面编辑保存验证\n');
  await editor.press('ControlOrMeta+s');
  await page.getByText('已保存到服务器',{exact:true}).waitFor();
  if(result.saved!=='桌面编辑保存验证\n')throw new Error('Editor save content differs');
  await page.getByRole('button',{name:'关闭文本编辑器',exact:true}).click();
  result.stage='upload';
  await page.getByLabel('选择上传文件',{exact:true}).setInputFiles({name:'upload-check.txt',mimeType:'text/plain',buffer:Buffer.from('desktop upload check')});
  await page.getByText('已上传',{exact:false}).first().waitFor();
  if(fixture)result.uploadBytes=fixture.uploadBytes-uploadStart;
  if(result.uploadBytes!==20)throw new Error('Upload bytes differ: '+result.uploadBytes);
  result.stage='terminal';
  await page.getByRole('button',{name:'在当前目录打开终端',exact:true}).click();
  const terminal=page.locator('.xterm-helper-textarea').last();
  await page.locator('.terminal-phase.running').waitFor();
  await terminal.focus();
  await page.keyboard.type('echo desktop-check');
  await page.keyboard.press('Enter');
  const deadline=Date.now()+5000;
  while((!result.terminalInput.includes('echo desktop-check\r')||!result.terminalAcks)&&Date.now()<deadline)await page.waitForTimeout(20);
  if(!result.terminalInput.includes('echo desktop-check\r')||!result.terminalAcks)throw new Error('Terminal input/output was not acknowledged: '+JSON.stringify(result));
  // Leave an actual dirty editor for a separate native-window close-guard check.
  result.stage='dirty editor';
  await page.getByRole('button',{name:'最小化终端',exact:true}).click();
  await page.getByRole('button',{name:'文件 /demo/check.txt',exact:true}).dblclick();
  await editor.fill('未保存的桌面关闭验证\n');
  return {...result,dirtyEditor:true};
}
