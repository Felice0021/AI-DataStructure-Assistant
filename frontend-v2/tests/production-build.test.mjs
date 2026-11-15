import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'

const files = await readdir('dist', { recursive: true })

test('production build excludes MSW and browser-test fixtures', async () => {
  assert.ok(files.includes('index.html'), 'run npm run build first')
  assert.ok(!files.some(file => /mock|worker|tests[\\/]/i.test(file)), 'unexpected mock/worker/test artifact')
  const scripts = files.filter(file => /\.(?:js|html|css)$/.test(file))
  assert.ok(scripts.some(file => file.endsWith('.js')))
  for (const file of scripts) {
    const content = await readFile(join('dist', file), 'utf8')
    assert.doesNotMatch(content, /mockServiceWorker|Mock Service Worker|setupWorker|msw\/browser|mockAnswered|evil\.example/, file)
  }
})

test('KaTeX styling and fonts are bundled locally', async () => {
  assert.ok(files.some(file => /KaTeX_Main-Regular.*\.woff2$/.test(file)))
  const styles = await Promise.all(files.filter(file => file.endsWith('.css')).map(file => readFile(join('dist', file), 'utf8')))
  assert.ok(styles.some(style => style.includes('.katex') && style.includes('KaTeX_Main-Regular')))
})
