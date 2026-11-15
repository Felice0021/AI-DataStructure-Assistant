import { test, expect, type Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import cases from '../../src/__tests__/fixtures/verified-trees.json' with { type: 'json' }
import { mockAnswered, mockKnowledgeBases, mockUser } from '../../src/mocks/fixtures'

async function openTree(page: Page, name: keyof typeof cases, data: unknown = cases[name]) {
  const answer = `服务端已校验的 ${name} 结构。[S1]\n\n\`\`\`text\n旧客户端保留的文字树\n\`\`\``
  const result = { ...mockAnswered, answer, sources: mockAnswered.sources.slice(0,1), tree_visualization:data }
  const conversation = { id:'tree-review',title:`${name} 树形图 · 合成布局验收`, updated_at:'2026-11-14T10:00:00Z' }
  await page.route('**/api/v2/**',async route=>{
    const path=new URL(route.request().url()).pathname
    let body:unknown
    if (path.endsWith('/auth/me')) body={user:mockUser}
    else if (path.endsWith('/knowledge-bases')) body={items:mockKnowledgeBases,total:mockKnowledgeBases.length}
    else if (path.endsWith('/conversations')) body={items:[conversation],total:1}
    else if (path.endsWith('/messages')) body={items:[
      {id:'question',seq:1,role:'user',content:`请展示 ${name} 的已验证树形图。`,metadata_json:{}},
      {id:'tree-answer',seq:2,role:'assistant',content:answer,metadata_json:{result}},
    ],total:2}
    else throw Error(`Unexpected API path: ${path}`)
    await route.fulfill({json:body})
  })
  await page.goto('/?conversation=tree-review')
}

for (const name of Object.keys(cases) as (keyof typeof cases)[]) {
  test(`${name}: real SVG, bounded layout, source interaction and contained scrolling`,async({page,baseURL},info)=>{
    const errors:string[]=[],external:string[]=[]
    page.on('pageerror',e=>errors.push(e.message))
    page.on('request',r=>{if(!r.url().startsWith(baseURL!))external.push(r.url())})
    await openTree(page,name)
    const graphic=page.locator('.verified-tree')
    await expect(graphic).toBeVisible()
    await expect(page.locator('.answer-text pre')).toHaveCount(0)
    if (cases[name].family === 'AVL') await expect(page.locator('.answer-text tbody tr')).toHaveCount(3)
    await expect(graphic.locator('svg')).toHaveCount(['LR','RL'].includes(name)?3:['LL','RR'].includes(name)?2:1)
    if (name==='B'||name==='B+') {
      await expect(graphic.locator('.tree-node circle')).toHaveCount(0)
      await expect(graphic.locator('.tree-node rect')).toHaveCount(cases[name].final.nodes.length)
    }
    const geometry=await graphic.locator('.tree-scroll').evaluateAll(regions=>regions.map(region=>{
      const el=region as HTMLElement,svg=el.querySelector('svg')!,box=svg.viewBox.baseVal
      const bounds=[...svg.querySelectorAll<SVGGraphicsElement>('.tree-node')].map(node=>{
        const b=node.getBBox(),m=node.transform.baseVal.consolidate()!.matrix
        return{x:b.x+m.e,y:b.y+m.f,width:b.width,height:b.height}
      })
      return{scroll:el.scrollWidth,client:el.clientWidth,viewWidth:box.width,viewHeight:box.height,bounds}
    }))
    for (const region of geometry) for (const node of region.bounds) {
      expect(node.x).toBeGreaterThanOrEqual(0);expect(node.y).toBeGreaterThanOrEqual(0)
      expect(node.x+node.width).toBeLessThanOrEqual(region.viewWidth)
      expect(node.y+node.height).toBeLessThanOrEqual(region.viewHeight)
    }
    const wide=graphic.locator('.tree-scroll').filter({has:page.locator('svg')})
    for(let i=0;i<await wide.count();i++) {
      const area=wide.nth(i)
      const edge=await area.evaluate(el=>{
        const svg=el.querySelector('svg')!;el.scrollLeft=0
        const left=svg.getBoundingClientRect().left,outerLeft=el.getBoundingClientRect().left
        el.scrollLeft=el.scrollWidth
        return{left,outerLeft,right:svg.getBoundingClientRect().right,outerRight:el.getBoundingClientRect().right}
      })
      expect(edge.left).toBeGreaterThanOrEqual(edge.outerLeft-1)
      expect(edge.right).toBeLessThanOrEqual(edge.outerRight+1)
      await area.evaluate(el=>{el.scrollLeft=0})
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    expect(await page.locator('.stream').evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true)
    await expect(page.locator('details.sources')).not.toHaveAttribute('open')
    await page.locator('.answer-text button.cite').first().click()
    await expect(page.locator('details.sources')).toHaveAttribute('open')
    await expect(page.locator('.source-item.is-active')).toHaveCount(1)
    // Browser clipboard exercised without reading any private browser state.
    await page.context().grantPermissions(['clipboard-read','clipboard-write'])
    await page.getByRole('button',{name:'复制回答',exact:true}).click()
    await expect(page.getByRole('button',{name:'已复制',exact:true})).toBeVisible()
    expect(await page.evaluate(()=>navigator.clipboard.readText())).toContain('旧客户端保留的文字树')
    // Refresh restores the same authenticated API history shape (synthetic routes, no production access).
    await page.reload();await expect(page.locator('.verified-tree')).toBeVisible()
    if (['LR','RL','BST','B','B+'].includes(name)) {
      const focus=page.locator('.tree-rotation').first()
      if(await focus.count()) await focus.locator('figcaption').first().scrollIntoViewIfNeeded()
      else await page.locator('.tree-figure figcaption').scrollIntoViewIfNeeded()
      await mkdir('docs/screenshots/verified-trees',{recursive:true})
      await page.screenshot({path:`docs/screenshots/verified-trees/${info.project.name}-${name.replace('+','plus')}.png`,animations:'disabled'})
    }
    if (info.project.name === 'mobile-390' && ['LR','RL'].includes(name)) {
      const frames=page.locator('.tree-figure')
      for (const index of [1,2]) {
        await frames.nth(index).scrollIntoViewIfNeeded()
        const bounds=(await frames.nth(index).boundingBox())!,stream=(await page.locator('.stream').boundingBox())!
        expect(bounds.y+bounds.height).toBeLessThanOrEqual(stream.y+stream.height+1)
        await page.screenshot({path:`docs/screenshots/verified-trees/mobile-390-${name}-${index === 1 ? 'intermediate' : 'after'}.png`,animations:'disabled'})
      }
    }
    expect(external).toEqual([]);expect(errors).toEqual([])
    expect(await page.evaluate(()=>navigator.serviceWorker.getRegistrations().then(r=>r.length))).toBe(0)
  })
}

test('unknown/injected structures keep the safe text fallback and do not create SVG',async({page})=>{
  await openTree(page,'LR',{...cases.LR,final:{...cases.LR.final,nodes:[{id:'n0',keys:['<img onerror=alert(1)>'],children:[]}]}})
  await expect(page.locator('.tree-svg')).toHaveCount(0)
  await expect(page.locator('.answer-text pre')).toContainText('旧客户端保留的文字树')
  await expect(page.locator('.answer-text img, .answer-text script')).toHaveCount(0)
})
