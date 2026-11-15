import { test,expect,type Page } from '@playwright/test'
import { createServer,type ServerResponse } from 'node:http'
import { mkdir } from 'node:fs/promises'
import { mockAnswered,mockKnowledgeBases,mockUser } from '../../src/mocks/fixtures'
import treeCases from '../../src/__tests__/fixtures/verified-trees.json' with { type:'json' }

/** Controlled network server, not a model and never a production Mock worker. */
async function prepare(page:Page,baseURL:string,kind:'answer'|'failure'|'tree'='answer') {
  const state={saved:false,loggedIn:true,ids:[] as string[],closed:0,active:null as ServerResponse|null,seq:0,body:null as any}
  const result={...mockAnswered,sources:mockAnswered.sources.slice(0,1),answer:'## 栈与队列\n\n**栈**使用后进先出；队列使用先进先出。[S1]\n\n- 栈：LIFO\n- 队列：FIFO\n\n时间复杂度 $O(1)$。\n\n```cpp\nstack.push(1);\n```',tree_visualization:kind==='tree'?treeCases.LR:null}
  const conversation={id:'11111111-1111-4111-8111-111111111111',title:'网络流式 · 合成验收',updated_at:'2026-11-14T10:00:00Z'}
  const messages=()=>state.saved?[
    {id:'question',seq:1,role:'user',content:state.body?.query??'合成问题',metadata_json:{}},
    {id:'answer',seq:2,role:'assistant',content:result.answer,metadata_json:{result}},
  ]:[]
  const write=(type:string,payload:unknown)=>{
    state.active?.write(`event: ${type}\nid: ${++state.seq}\ndata: ${JSON.stringify({type,seq:state.seq,request_id:state.body.request_id,payload})}\n\n`)
  }
  const server=createServer(async(req,res)=>{
    res.setHeader('Access-Control-Allow-Origin',baseURL);res.setHeader('Access-Control-Allow-Credentials','true')
    res.setHeader('Access-Control-Allow-Headers','Content-Type, X-CSRF-Token');res.setHeader('Access-Control-Allow-Methods','POST, OPTIONS')
    if(req.method==='OPTIONS'){res.writeHead(204);res.end();return}
    let body='';for await(const bytes of req)body+=bytes
    state.body=JSON.parse(body);state.ids.push(state.body.request_id);state.active=res;state.seq=0
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-store, no-transform'});res.flushHeaders()
    write('status',{stage:'accepted',preview:false})
    res.on('close',()=>{state.closed++})
    if(state.saved){write('status',{stage:'validating',preview:false});write('result',{result});res.end();return}
    write('status',{stage:'retrieving',preview:false});write('reset',{});write('status',{stage:'generating',preview:kind!=='tree'})
    if(kind!=='tree')write('draft',{text:'## 栈与队列\n\n**栈采用后进先出**，队列采用先进先出。[S1]\n\n- 栈：LIFO\n- 队列：FIFO\n\n[外部站点](https://example.com)\n\n```cpp\nstack.push(1);'+(kind==='failure'?'\n<script>window.__streamXss=true</script>':'')})
    // Intentionally wait on a test-controlled barrier, never a timer/typing simulation.
  })
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
  const address=server.address();if(!address||typeof address==='string')throw Error('missing server')
  const endpoint=`http://127.0.0.1:${address.port}/sse`
  await page.route('**/api/v2/**',async route=>{
    const path=new URL(route.request().url()).pathname,method=route.request().method()
    if(path.endsWith('/ask-stream')) {await route.continue({url:endpoint});return}
    let body:unknown
    if(path.endsWith('/auth/me')) {
      if(!state.loggedIn){await route.fulfill({status:401,json:{error:{code:'unauthorized',message:'Sign in'}}});return}
      body={user:mockUser}
    } else if(path.endsWith('/auth/csrf')) body={csrf_token:'mock-only-not-a-backend-token'}
    else if(path.endsWith('/auth/logout')) {state.loggedIn=false;await route.fulfill({status:204});return}
    else if(path.endsWith('/knowledge-bases'))body={items:mockKnowledgeBases,total:mockKnowledgeBases.length}
    else if(path.endsWith('/conversations')&&method==='POST')body={conversation}
    else if(path.endsWith('/conversations'))body={items:state.body?[conversation]:[],total:state.body?1:0}
    else if(path.endsWith('/messages'))body={items:messages(),total:messages().length}
    else if(path.endsWith('/cloud-consents')||path.endsWith('/targets'))body=['embedding','reranking','generation'].map(purpose=>({purpose,service_key:purpose,revoked_at:null}))
    else throw Error(`Unexpected test API: ${method} ${path}`)
    await route.fulfill({json:body})
  })
  await page.goto('/')
  return {
    state,
    finish(){
      if(kind==='failure')write('error',{status:502,code:'invalid_citations',message:'Answer unavailable'})
      else {write('status',{stage:'validating',preview:false});write('status',{stage:'saving',preview:false});state.saved=true;write('result',{result})}
      state.active?.end()
    },
    async close(){state.active?.destroy();server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))},
  }
}

async function send(page:Page){await page.getByRole('textbox',{name:'向 AI 助教提问',exact:true}).fill('栈和队列有什么区别？');await page.getByRole('button',{name:'发送问题',exact:true}).click()}

for(const kind of ['answer','failure','tree'] as const) test(`incremental ${kind}: preview/validation/history at actual network speed`,async({page,baseURL},info)=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  const harness=await prepare(page,baseURL!,kind)
  try {
    await send(page)
    await expect(page.getByRole('button',{name:'停止生成'})).toBeVisible()
    await expect(page.getByRole('status')).toContainText('正在生成回答')
    expect(harness.state.saved).toBe(false)
    if(kind==='tree') {await expect(page.locator('.tree-svg')).toHaveCount(0);await expect(page.locator('.stream-draft')).toHaveCount(0)}
    else {
      await expect(page.locator('.draft-text')).toContainText('栈采用后进先出')
      await expect(page.locator('.stream-draft')).toContainText('尚未校验')
      await expect(page.locator('.draft-text h2')).toHaveText('栈与队列')
      await expect(page.locator('.draft-text strong')).toHaveText('栈采用后进先出')
      await expect(page.locator('.draft-text li')).toHaveCount(2)
      await expect(page.locator('.draft-text pre code')).toContainText('stack.push(1);')
      await expect(page.locator('.stream-draft button.cite,.stream-draft .copy-answer,.stream-draft a,.stream-draft script,.stream-draft .katex')).toHaveCount(0)
      expect(await page.locator('.draft-text').evaluate(element => !element.dispatchEvent(new Event('copy',{bubbles:true,cancelable:true})))).toBe(true)
      expect(await page.evaluate(()=>(window as unknown as Record<string,unknown>).__streamXss)).toBeUndefined()
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    if(kind==='answer'){
      await mkdir('docs/screenshots/streaming',{recursive:true})
      await page.screenshot({path:`docs/screenshots/streaming/${info.project.name}-draft.png`,animations:'disabled'})
    }
    harness.finish()
    await expect(page.locator('.stream-draft')).toHaveCount(0)
    if(kind==='failure'){
      await expect(page.getByRole('alert')).toContainText('本次回答未完成')
      await expect(page.locator('[data-testid="answer-success"]')).toHaveCount(0)
      expect(harness.state.saved).toBe(false)
    } else {
      await expect(page.locator('[data-testid="answer-success"]')).toBeVisible()
      if(kind==='tree')await expect(page.locator('.tree-svg')).toHaveCount(3)
      else {
        await expect(page.locator('.answer-text strong').first()).toHaveText('栈')
        await expect(page.locator('.answer-text .katex')).toHaveCount(1)
        await expect(page.locator('.answer-text pre code')).toContainText('stack.push(1)')
      }
      await page.locator('button.cite').first().click();await expect(page.locator('details.sources')).toHaveAttribute('open')
      await page.reload();await expect(page.locator('[data-testid="answer-success"]')).toBeVisible()
      if(kind==='answer')await page.screenshot({path:`docs/screenshots/streaming/${info.project.name}-validated.png`,animations:'disabled'})
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
      await page.getByRole('button',{name:'打开导航'}).count().then(async n=>{if(n&&await page.getByRole('button',{name:'打开导航'}).isVisible())await page.getByRole('button',{name:'打开导航'}).click()})
      await page.getByRole('button',{name:'退出',exact:true}).click();await expect(page.locator('.answer-view')).toHaveCount(0)
    }
    expect(errors).toEqual([])
    expect(await page.evaluate(()=>navigator.serviceWorker.getRegistrations().then(r=>r.length))).toBe(0)
  } finally {await harness.close()}
})

test('cancel withdraws the network draft; retry reuses request_id and stores exactly one pair',async({page,baseURL})=>{
  const h=await prepare(page,baseURL!)
  try {
    await send(page);await expect(page.locator('.draft-text')).toBeVisible()
    await page.getByRole('button',{name:'停止生成'}).click();await expect(page.locator('.draft-text')).toHaveCount(0)
    await expect.poll(()=>h.state.closed).toBeGreaterThan(0)
    expect(h.state.saved).toBe(false)
    await page.getByRole('button',{name:'重试',exact:true}).click();await expect(page.locator('.draft-text')).toBeVisible()
    expect(h.state.ids).toHaveLength(2);expect(h.state.ids[0]).toBe(h.state.ids[1])
    h.finish();await expect(page.locator('.message.assistant')).toHaveCount(1)
    await page.reload();await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.user')).toHaveCount(1)
  } finally {await h.close()}
})

test('refresh during generation closes the old stream without resending or restoring a draft',async({page,baseURL})=>{
  const h=await prepare(page,baseURL!)
  try {
    await send(page);await expect(page.locator('.draft-text')).toBeVisible()
    await page.reload();await expect(page.locator('.draft-text')).toHaveCount(0)
    await expect.poll(()=>h.state.closed).toBeGreaterThan(0)
    await expect(page.locator('.message.assistant')).toHaveCount(0)
    expect(h.state.ids).toHaveLength(1);expect(h.state.saved).toBe(false)
  } finally {await h.close()}
})

test('logout while generating aborts the stream and removes all private draft state',async({page,baseURL})=>{
  const h=await prepare(page,baseURL!)
  try {
    await send(page);await expect(page.locator('.draft-text')).toBeVisible()
    const menu=page.getByRole('button',{name:'打开导航'})
    if(await menu.isVisible())await menu.click()
    await page.getByRole('button',{name:'退出',exact:true}).click()
    await expect(page.locator('.workspace')).toHaveCount(0)
    await expect(page.locator('.draft-text')).toHaveCount(0)
    await expect.poll(()=>h.state.closed).toBeGreaterThan(0)
    expect(h.state.loggedIn).toBe(false);expect(h.state.saved).toBe(false)
  } finally {await h.close()}
})
