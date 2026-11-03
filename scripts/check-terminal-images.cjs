// Synthetic local terminal image check; no SSH or external image fetches.
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
async function main(){
 const {createServer}=await import(require('node:url').pathToFileURL(path.join(root,'frontend/node_modules/vite/dist/node/index.js')).href);
 const {chromium,webkit}=require(path.join(root,'work/desktop-benchmark/node_modules/playwright'));
 const server=await createServer({root:path.join(root,'frontend'),server:{host:'127.0.0.1',port:0},logLevel:'error'});await server.listen();
 const url=server.resolvedUrls.local[0],results=[];
 try{for(const [name,engine,fallback] of [['chromium',chromium,false],['webkit',webkit,true]]){
  const browser=await engine.launch({headless:true,...(name==='chromium'?{channel:'msedge'}:{})});try{const page=await browser.newPage({viewport:{width:900,height:600}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.route(url,route=>route.fulfill({contentType:'text/html',body:'<html><head><link rel="stylesheet" href="/node_modules/@xterm/xterm/css/xterm.css"></head><body><div id="term"></div></body></html>'}));await page.goto(url);fs.mkdirSync(path.join(root,'work/feature8'),{recursive:true});await page.exposeFunction('captureTerminalImage',protocol=>page.screenshot({path:path.join(root,'work/feature8/'+name+'-'+protocol+'.png')}));
   const result=await page.evaluate(async({fallback})=>{
    if(fallback)Object.defineProperty(window,'createImageBitmap',{value:undefined,configurable:true});
    const {Terminal}=await import('/node_modules/@xterm/xterm/lib/xterm.mjs');
    const {SafeImageAddon}=await import('/src/SafeImageAddon.ts');const {IMAGE_OPTIONS}=await import('/src/terminalImages.ts');
    const term=new Terminal({cols:60,rows:16,allowProposedApi:true});term.open(document.getElementById('term'));const addon=new SafeImageAddon({...IMAGE_OPTIONS});term.loadAddon(addon);
    const write=data=>new Promise(resolve=>term.write(data,resolve));const sample=()=>{for(let y=0;y<term.buffer.active.length;y++)for(let x=0;x<term.cols;x++){const canvas=addon.getImageAtBufferCell(x,y);if(canvas)return {width:canvas.width,height:canvas.height,pixel:Array.from(canvas.getContext('2d').getImageData(0,0,1,1).data)}}};
    const png=document.createElement('canvas');png.width=8;png.height=8;png.getContext('2d').fillStyle='#ff0000';png.getContext('2d').fillRect(0,0,8,8);const data=png.toDataURL().split(',')[1];
    await write('\x1b]1337;File=inline=1;size='+atob(data).length+':'+data+'\x07');const iip=sample();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));iip.renderedCanvases=document.querySelectorAll('canvas').length;await window.captureTerminalImage('iip');addon.reset();await write('\x1bc');
    await write('\x1bPq"1;1;8;6#0;2;100;0;0#0!8~\x1b\\');const sixel=sample();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));sixel.renderedCanvases=document.querySelectorAll('canvas').length;await window.captureTerminalImage('sixel');addon.reset();await write('\x1bc');
    // A valid PNG header with damaged body exercises decoder failure handling.
    const bad=data.slice(0,44)+'AAAA';await write('\x1b]1337;File=inline=1;size='+atob(bad).length+':'+bad+'\x07');await write('AFTER-CORRUPT');
    const text=term.buffer.active.getLine(term.buffer.active.cursorY).translateToString(true);await write('\x1b]1337;File=inline=0;size='+atob(data).length+':'+data+'\x07');const downloadUsage=addon.storageUsage;
    let lateDecode;
    if(!fallback){
     const native=window.createImageBitmap;let release;
     window.createImageBitmap=(...args)=>new Promise(resolve=>{release=()=>native(...args).then(resolve)});
     await write('\r\n');const decoding=write('\x1b]1337;File=inline=1;size='+atob(data).length+':'+data+'\x07');
     await decoding;await write('AFTER-TIMEOUT');release();await new Promise(r=>setTimeout(r,100));
     const afterTimeout=addon.storageUsage;const resumed=term.buffer.active.getLine(term.buffer.active.cursorY).translateToString(true);
     const disposing=write('\x1b]1337;File=inline=1;size='+atob(data).length+':'+data+'\x07');
     await new Promise(r=>setTimeout(r,20));addon.dispose();await disposing;release();await new Promise(r=>setTimeout(r,100));
     lateDecode={afterTimeout,resumed,afterDispose: addon.storageUsage};window.createImageBitmap=native;
    }
    const usage=addon.storageUsage;return {iip,sixel,text,usage,downloadUsage,lateDecode,canvasCount:document.querySelectorAll('canvas').length};
   },{fallback});
   assert.ok(result.iip.renderedCanvases>0);assert.ok(result.sixel.renderedCanvases>0);assert.equal(result.iip.width,8);assert.deepEqual(result.iip.pixel,[255,0,0,255]);assert.equal(result.sixel.width,8);assert.deepEqual(result.sixel.pixel,[255,0,0,255]);assert.ok(result.text.includes('AFTER-CORRUPT'));assert.equal(result.downloadUsage,0);assert.deepEqual(errors,[]);if(result.lateDecode){assert.equal(result.lateDecode.afterTimeout,0);assert.ok(result.lateDecode.resumed.includes('AFTER-TIMEOUT'));assert.equal(result.lateDecode.afterDispose,0)}
   fs.mkdirSync(path.join(root,'work/feature8'),{recursive:true});await page.screenshot({path:path.join(root,'work/feature8/'+name+'.png')});results.push({name,fallback,...result,errors});
  }finally{await browser.close()}
 }}finally{await server.close()}
 console.log(JSON.stringify(results,null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1});


