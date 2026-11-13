<script lang="ts">
import MarkdownIt from 'markdown-it'
import { defineComponent, h, type PropType, type VNodeChild } from 'vue'
import type { AnswerSource } from '@/types/api'

// Model output is untrusted. Markdown tokens are rendered as Vue nodes, never HTML.
const markdown = new MarkdownIt({ html: false, linkify: false, breaks: false })
type Token = ReturnType<typeof markdown.parse>[number]
const tags = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li', 'strong', 'em', 's', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td'])

export default defineComponent({
  props: { text: { type: String, required: true }, sources: { type: Array as PropType<AnswerSource[]>, required: true } },
  emits: ['cite'],
  setup(props, { emit }) {
    function renderTokens(tokens: Token[], known: Set<string>): VNodeChild[] {
      const root: VNodeChild[] = []
      const stack: { children: VNodeChild[]; tag: string }[] = [{ children: root, tag: '' }]
      const append = (node: VNodeChild) => stack[stack.length - 1]!.children.push(node)
      for (const token of tokens) {
        if (token.type === 'inline') { renderTokens(token.children ?? [], known).forEach(append); continue }
        if (token.nesting === 1 && tags.has(token.tag)) {
          const children: VNodeChild[] = []
          const attrs: Record<string, string> = {}
          if (token.tag === 'a') {
            const href = token.attrGet('href') ?? ''
            if (/^(https?:|mailto:)/i.test(String(href)) && markdown.validateLink(String(href))) { attrs.href = String(href); attrs.rel = 'noopener noreferrer nofollow' }
          }
          if (token.tag === 'ol' && token.attrGet('start')) attrs.start = String(token.attrGet('start'))
          append(h(token.tag, attrs, children)); stack.push({ children, tag: token.tag }); continue
        }
        if (token.nesting === -1 && tags.has(token.tag)) { if (stack.length > 1) stack.pop(); continue }
        if (token.type === 'text') {
          // Inline code and fenced code are separate token types and never enter this branch.
          const inLink = stack.some((item) => item.tag === 'a')
          const parts = token.content.split(/(\[S[1-9]\d*\])/g)
          for (const part of parts) {
            if (!part) continue
            if (!inLink && /^\[S[1-9]\d*\]$/.test(part)) {
              append(known.has(part)
                ? h('button', { type: 'button', class: 'cite', title: `查看来源 ${part}`, onClick: () => emit('cite', part) }, part)
                : h('span', { class: 'cite-unknown', title: '本次回答未返回该来源' }, part))
            } else append(part)
          }
        } else if (token.type === 'code_inline') append(h('code', token.content))
        else if (token.type === 'fence' || token.type === 'code_block') {
          const language = token.info.trim().split(/\s+/)[0] ?? ''
          append(h('pre', [h('code', { class: /^[\w+-]{1,40}$/.test(language) ? `language-${language}` : undefined }, token.content)]))
        } else if (token.type === 'softbreak') append('\n')
        else if (token.type === 'hardbreak') append(h('br'))
        else if (token.type === 'hr') append(h('hr'))
        else if (token.type === 'image') append(token.content)
      }
      return root
    }
    return () => h('div', { class: 'answer-text' }, renderTokens(markdown.parse(props.text, {}), new Set(props.sources.map((s) => s.citation_id))))
  },
})
</script>

<style scoped>
.answer-text { font-size: 15px; line-height: 1.8; color: var(--ink); overflow-wrap: anywhere; }
.answer-text :deep(p) { margin: 0 0 0.9em; white-space: pre-wrap; }
.answer-text :deep(h1), .answer-text :deep(h2), .answer-text :deep(h3), .answer-text :deep(h4) { margin: 1em 0 0.45em; line-height: 1.35; }
.answer-text :deep(ul), .answer-text :deep(ol) { padding-left: 1.5em; margin: 0.5em 0 1em; }
.answer-text :deep(blockquote) { margin: 1em 0; padding-left: 1em; border-left: 3px solid var(--line); color: var(--muted); }
.answer-text :deep(pre), .answer-text :deep(table) { display: block; max-width: 100%; overflow-x: auto; }
.answer-text :deep(pre) { padding: 12px; background: #f5f5f5; border-radius: 8px; line-height: 1.5; }
.answer-text :deep(code) { font-family: ui-monospace, monospace; }
.answer-text :deep(table) { border-collapse: collapse; margin: 1em 0; }
.answer-text :deep(th), .answer-text :deep(td) { border: 1px solid var(--line); padding: 6px 10px; }
.answer-text :deep(.cite), .answer-text :deep(.cite-unknown) { display: inline; padding: 0 3px; margin: 0 1px; border: 0; border-radius: 4px; font-size: 12px; vertical-align: 1px; }
.answer-text :deep(.cite) { background: #f1f1f1; color: #404040; cursor: pointer; }
.answer-text :deep(.cite-unknown) { background: #f1f1f1; color: #737373; }
.answer-text :deep(.cite:focus-visible) { outline: 2px solid var(--brand); outline-offset: 1px; }
</style>
