// Cross-platform WebKit check; does not prove native Tauri window integration.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'..');
async function main(){
  let playwright;
  try{playwright=createRequire(path.join(root,'work/desktop-benchmark/package.json'))('playwright')}catch{}
  if(!playwright&&process.env.LOCALAPPDATA)for(const folder of fs.readdirSync(path.join(process.env.LOCALAPPDATA,'npm-cache/_npx'))){
      const pkg=path.join(process.env.LOCALAPPDATA,'npm-cache/_npx',folder,'node_modules/playwright/package.json');
      if(fs.existsSync(pkg)){playwright=createRequire(pkg)('playwright');break}
  }
  if(!playwright)throw new Error('Install playwright and ws into work/desktop-benchmark first');
  fs.mkdirSync(path.join(root,'work/performance-round2'),{recursive:true});
  const fixture=await require('./desktop-benchmark-server.cjs')(path.join(root,'frontend/dist'),require(path.join(root,'work/desktop-benchmark/node_modules/ws')).WebSocketServer);
  let browser;
  const output={platform:process.platform==='darwin'?'macOS Playwright WebKit; native Tauri window lifecycle still requires validation':'Windows WebKit port; does not prove native macOS runtime',cases:[]};
  try{
    browser=await playwright.webkit.launch({headless:true});output.version=browser.version();
    for(const legacy of [false,true]){
      const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage();
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      if(legacy)await context.addInitScript(()=>{
        Object.defineProperty(Crypto.prototype,'randomUUID',{value:undefined,configurable:true});
        Object.defineProperty(Array.prototype,'at',{value:undefined,configurable:true});
        Object.defineProperty(window,'WebGL2RenderingContext',{value:undefined,configurable:true});
      });
      await page.goto('http://127.0.0.1:'+fixture.port);
      await page.getByRole('button',{name:'只看机器 bench-01',exact:true}).waitFor();
      assert.equal(await page.locator('.machine').count(),48);
      const viewports=[];
      for(const width of [480,800,1440]){
        await page.setViewportSize({width,height:900});await page.waitForTimeout(100);
        const measured=await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth}));
        assert.ok(measured.documentWidth<=measured.width);viewports.push(measured);
      }
      await page.getByRole('button',{name:'精度对比',exact:true}).click();
      await page.getByRole('heading',{name:'基准日志',exact:true}).waitFor();
      await page.getByRole('button',{name:'设置',exact:true}).click();
      await page.getByRole('heading',{name:'设置',exact:true}).waitFor();
      const launchSettings=page.locator('.settings-page').filter({has:page.getByRole('heading',{name:'启动与桌面浮窗',exact:true})});
      await launchSettings.getByText('桌面资源浮窗目前仅支持 Windows。',{exact:true}).waitFor();
      assert.equal(await launchSettings.getByRole('checkbox').count(),0);
      assert.equal(await launchSettings.getByRole('radio',{name:'桌面窗口',exact:false}).isEnabled(),true);
      await page.getByRole('button',{name:'算力总览',exact:true}).click();
      await page.getByRole('button',{name:'打开 bench-01 终端',exact:true}).click();
      await page.locator('.xterm-helper-textarea').waitFor({state:'attached'});
      await page.waitForTimeout(500);
      fixture.startPhase(1,64*1024);await page.waitForTimeout(2000);const stream=await fixture.stopPhase();
      assert.ok(stream.ackBytes>0);assert.equal(stream.ackBytes,stream.sentBytes);assert.equal(stream.pendingMessages,0);
      const renderer=await page.locator('.terminal-screen.active').getAttribute('data-renderer')||'dom';
      if(legacy)assert.equal(renderer,'dom');
      const fileAndTerminalFlow=await require('./check-desktop-flows.cjs')(page,fixture);
      await page.screenshot({path:path.join(root,'work/performance-round2/webkit-'+(legacy?'fallback':'normal')+'.png')});
      assert.deepEqual(errors,[]);
      output.cases.push({legacyApiFallback:legacy,viewports,renderer,ackBytes:stream.ackBytes,fileAndTerminalFlow,errors});await context.close();
    }
  }finally{await browser?.close();await fixture.close()}
  fs.writeFileSync(path.join(root,'work/performance-round2/webkit-compat.json'),JSON.stringify(output,null,2));console.log(JSON.stringify(output));
}
main().catch(error=>{console.error(error);process.exitCode=1});
