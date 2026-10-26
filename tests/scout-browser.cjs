// Read-only check against the working scouting interface. Does not start a run or save applications.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXE||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8765/#discover');
    await page.getByRole('heading',{name:'Discover',exact:true}).waitFor();
    await page.getByRole('button',{name:'Scholarships',exact:true}).click();
    await page.getByRole('heading',{name:'Discover',exact:true}).waitFor();
    await page.locator('.opportunity-grid').getByRole('heading',{name:'ISACA Foundation',exact:true}).waitFor();
    await page.locator('.opportunity-grid').getByRole('heading',{name:'Cloudflare',exact:true}).waitFor({state:'detached'});
    assert.equal(await page.locator('.opportunity-grid').getByRole('heading',{name:'Cloudflare',exact:true}).count(),0);
    await page.locator('.opportunity-grid').getByRole('link',{name:'Evidence'}).first().click();
    await page.getByRole('heading',{name:'Blockers',exact:true}).waitFor();
    await page.getByText('Individual awards, current cycles, deadlines, and eligibility require review.',{exact:false}).waitFor();
    await page.locator('nav a[href="#discover"]').click();
    await page.getByRole('heading',{name:'Discover',exact:true}).waitFor();
    await page.getByRole('button',{name:'All',exact:true}).click();
    await page.getByRole('heading',{name:'Discover',exact:true}).waitFor();
    await page.screenshot({path:path.resolve('.tmp/scout-desktop.png'),fullPage:true});
    await page.setViewportSize({width:320,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    console.log('Scouting browser checks passed: coverage, runs, scope filters, evidence detail, review gates, and narrow layout.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
