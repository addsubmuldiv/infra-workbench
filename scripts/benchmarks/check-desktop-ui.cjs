async page => {
  const results=[];
  for(const width of [480,800,1440]){
    await page.setViewportSize({width,height:900});
    await page.waitForTimeout(300);
    results.push(await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,
      machines:document.querySelectorAll('.machine').length,sidebar:getComputedStyle(document.querySelector('.sidebar')).width})));
  }
  const last=page.locator('.machine').last();
  await last.scrollIntoViewIfNeeded();
  const rendered=await last.evaluate(el=>({height:el.getBoundingClientRect().height,devices:el.querySelectorAll('.device-table tbody tr').length}));
  await page.screenshot({path:'work/desktop-responsive.png'});
  return {viewports:results,lastMachine:rendered};
}
