import { test, expect, type Page } from '@playwright/test'
import { mockAnswered, mockKnowledgeBases, mockUser } from '../../src/mocks/fixtures'

const answer = String.raw`## 二分查找与复杂度

**归并排序** $O(n \log n)$，平方复杂度 $O(n^2)$，二分查找 $O(\log n)$。数组元素 $a[i]$，求和 $\sum_{i=1}^{n} i$。[S1]

$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
$$

括号写法：\( O(\log n) \)。独立公式的另一种写法：

\[
\sqrt{n^2} + \overbrace{a+b}^{n}
\]

| 步骤 | low | high | mid | 比较 | 区间更新 | 时间复杂度 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | $0$ | $n-1$ | $\lfloor(low+high)/2\rfloor$ | $a[mid] < target$ | $low = mid + 1$ | $O(\log n)$ [S1] |
| 2 | $mid+1$ | $n-1$ | $\lfloor(low+high)/2\rfloor$ | $a[mid] > target$ | $high = mid - 1$ | $O(\log n)$ |

转义美元符号：\$5；代码中的公式保持原样：` + '`$O(n^2)$`' + String.raw`

` + '```python\nprice = "$5"  # $O(n)$ [S1]\n```' + String.raw`

不完整公式：$\frac{1}{$；危险命令：$\includegraphics{https://evil.example/track.png}$。

<script>window.__injected = true</script><img src="https://evil.example/x" onerror="alert(1)">
`

test('production answer renders formulas, contains tables and keeps citations usable', async ({ page, baseURL }, testInfo) => {
  const pageErrors: string[] = []
  const externalRequests: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('request', request => {
    if (!request.url().startsWith(baseURL!) && !request.url().includes('/api/v2/')) externalRequests.push(request.url())
  })
  await openAnswer(page, answer)
  const rendered = page.locator('.answer-text')
  await expect(rendered.locator('.katex')).toHaveCount(21)
  await expect(rendered.locator('.math-display .katex-display')).toHaveCount(2)
  await expect(rendered.locator('.math-fallback')).toHaveCount(1)
  await expect(rendered.locator('pre code')).toHaveText('price = "$5"  # $O(n)$ [S1]')
  await expect(rendered.locator('p > code')).toHaveText('$O(n^2)$')
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.fonts.check('16px KaTeX_Main'))).toBe(true)

  const sizes = await page.evaluate(() => {
    const table = document.querySelector<HTMLElement>('.answer-table-scroll')!
    const stream = document.querySelector<HTMLElement>('.stream')!
    return { page: document.documentElement.scrollWidth, viewport: innerWidth, stream: stream.scrollWidth, streamClient: stream.clientWidth, table: table.scrollWidth, tableClient: table.clientWidth }
  })
  expect(sizes.page).toBeLessThanOrEqual(sizes.viewport)
  expect(sizes.stream).toBeLessThanOrEqual(sizes.streamClient)
  expect(sizes.table).toBeGreaterThan(sizes.tableClient)
  for (const title of ['low', 'high']) {
    const heading = rendered.getByRole('columnheader', { name: title, exact: true })
    expect(await heading.evaluate(element => getComputedStyle(element).whiteSpace)).toBe('nowrap')
    expect((await heading.boundingBox())!.height).toBeLessThan(50)
  }
  expect(await rendered.locator('td .answer-math').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).whiteSpace === 'nowrap' && node.scrollWidth <= node.clientWidth + 1))).toBe(true)
  const scroll = rendered.getByRole('region', { name: '回答表格，可横向滚动' })
  await scroll.focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => scroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
  await scroll.evaluate(element => { element.scrollLeft = 0; (element as HTMLElement).blur() })
  await page.locator('.stream').evaluate(element => { element.scrollTop = 0 })
  await page.screenshot({ path: testInfo.outputPath('answer-math.png'), fullPage: true, animations: 'disabled' })

  const sources = page.locator('details.sources')
  await expect(sources).not.toHaveAttribute('open')
  await rendered.locator('button.cite').first().click()
  await expect(sources).toHaveAttribute('open')
  await expect(sources.locator('.source-item.is-active')).toHaveCount(1)
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__injected)).toBeUndefined()
  expect(externalRequests).toEqual([])
  expect(pageErrors).toEqual([])
  expect(await page.evaluate(() => navigator.serviceWorker.getRegistrations().then(items => items.length))).toBe(0)
})

async function openAnswer(page: Page, answer: string): Promise<void> {
  const result = { ...mockAnswered, answer, sources: mockAnswered.sources.slice(0, 1) }
  const conversation = { id: 'math-review', title: '二分查找与复杂度', updated_at: '2026-11-13T10:00:00Z' }
  await page.route('**/api/v2/**', async route => {
    const path = new URL(route.request().url()).pathname
    let body: unknown
    if (path.endsWith('/auth/me')) body = { user: mockUser }
    else if (path.endsWith('/knowledge-bases')) body = { items: mockKnowledgeBases, total: mockKnowledgeBases.length }
    else if (path.endsWith('/conversations')) body = { items: [conversation], total: 1 }
    else if (path.endsWith('/messages')) body = { items: [{ id: 'answer-1', seq: 1, role: 'assistant', content: answer, metadata_json: { result } }], total: 1 }
    else throw new Error(`Unexpected test API request: ${path}`)
    await route.fulfill({ json: body })
  })
  await page.goto('/?conversation=math-review')
}

test('long inline and display formulas remain fully reachable inside their own scroll areas', async ({ page }) => {
  const formula = Array.from({ length: 60 }, (_, i) => `a_{${i + 1}}`).join(' + ')
  await openAnswer(page, `$${formula}$\n\n$$${formula}$$`)
  await expect(page.locator('.answer-math')).toHaveCount(2)
  await page.evaluate(() => document.fonts.ready)
  const geometry = await page.locator('.answer-math').evaluateAll(nodes => nodes.map(node => {
    const element = node as HTMLElement
    element.scrollLeft = 0
    const start = element.querySelector('.katex-base')!.getBoundingClientRect().left
    const left = element.getBoundingClientRect().left
    element.scrollLeft = element.scrollWidth
    const bases = element.querySelectorAll('.katex-base')
    const end = bases[bases.length - 1]!.getBoundingClientRect().right
    return { width: element.clientWidth, content: element.scrollWidth, start, left, end, right: element.getBoundingClientRect().right }
  }))
  for (const formula of geometry) {
    expect(formula.content).toBeGreaterThan(formula.width)
    expect(formula.start).toBeGreaterThanOrEqual(formula.left - 1)
    expect(formula.end).toBeLessThanOrEqual(formula.right + 1)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
