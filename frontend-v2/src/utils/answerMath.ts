import type { MarkdownIt } from 'markdown-it'
import katex from 'katex'
import { h, type VNodeChild } from 'vue'
import 'katex/dist/katex.min.css'

const MAX_FORMULA_LENGTH = 4096

function escaped(source: string, index: number): boolean {
  let slashes = 0
  while (index > 0 && source[--index] === '\\') slashes++
  return slashes % 2 === 1
}

function closingDelimiter(source: string, delimiter: string, start: number): number {
  let end = source.indexOf(delimiter, start)
  while (end !== -1 && escaped(source, end)) end = source.indexOf(delimiter, end + delimiter.length)
  return end
}

// Rules run before Markdown escapes; code tokens are consumed by Markdown itself.
export function answerMath(markdown: MarkdownIt): void {
  markdown.inline.ruler.before('escape', 'answer_math', (state, silent) => {
    const start = state.pos
    const source = state.src
    const open = ['$$', '\\[', '\\(', '$'].find((delimiter) => source.startsWith(delimiter, start))
    if (!open) return false
    const close = open === '\\[' ? '\\]' : open === '\\(' ? '\\)' : open
    const end = closingDelimiter(source, close, start + open.length)
    const content = source.slice(start + open.length, end)
    // Single dollars do not consume currency or span paragraphs/lines.
    if (end < 0 || !content.trim() || (open === '$' && (/^\s|\s$|\n/.test(content) || /\d/.test(source[end + 1] ?? '')))) {
      if (open.startsWith('\\')) {
        if (!silent) state.push('text', '', 0).content = open
        state.pos += open.length
        return true
      }
      return false
    }
    if (!silent) {
      const token = state.push(open === '$$' || open === '\\[' ? 'math_display' : 'math_inline', '', 0)
      token.content = content
      token.markup = open
    }
    state.pos = end + close.length
    return true
  })

  markdown.block.ruler.before('fence', 'answer_math_block', (state, startLine, endLine, silent) => {
    if (state.sCount[startLine]! - state.blkIndent >= 4) return false
    const start = state.bMarks[startLine]! + state.tShift[startLine]!
    const firstLine = state.src.slice(start, state.eMarks[startLine])
    const open = firstLine.startsWith('$$') ? '$$' : firstLine.startsWith('\\[') ? '\\[' : null
    if (!open) return false
    const close = open === '$$' ? '$$' : '\\]'
    let line = startLine
    let end = -1
    for (; line < endLine; line++) {
      if (line > startLine && state.sCount[line]! < state.blkIndent) break
      const lineStart = line === startLine ? start + open.length : state.bMarks[line]! + state.tShift[line]!
      const lineText = state.src.slice(lineStart, state.eMarks[line])
      const index = closingDelimiter(lineText, close, 0)
      if (index >= 0 && !lineText.slice(index + close.length).trim()) { end = lineStart + index; break }
    }
    if (end < 0) return false
    if (silent) return true
    const token = state.push('math_block', '', 0)
    token.content = state.getLines(startLine, line + 1, state.blkIndent, false)
      .trim().slice(open.length, -close.length)
    token.markup = open
    token.block = true
    token.map = [startLine, line + 1]
    state.line = line + 1
    return true
  }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] })
}

// Only KaTeX-generated markup reaches this converter. Model HTML never does.
// No links, resources, handlers, arbitrary attributes or arbitrary CSS survive.
const mathTags = new Set('span math semantics annotation mrow mi mo mn mtext mspace msup msub msubsup mfrac msqrt mroot munder mover munderover mtable mtr mtd menclose mpadded mphantom mstyle mmultiscripts mprescripts none svg path line'.split(' '))
const mathAttrs = new Set('class aria-hidden xmlns display encoding mathvariant stretchy fence separator accent accentunder lspace rspace columnalign rowalign columnspacing rowspacing columnlines rowlines width height depth viewBox preserveAspectRatio d fill stroke stroke-width x1 x2 y1 y2'.split(' '))
const lengthStyles = new Set('height width min-width top bottom left right margin-left margin-right margin-top margin-bottom padding-left padding-right padding-top padding-bottom vertical-align font-size border-bottom-width border-top-width border-right-width border-left-width'.split(' '))

function mathNode(node: Node): VNodeChild {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? ''
  if (node.nodeType !== Node.ELEMENT_NODE) return null
  const element = node as Element
  if (!mathTags.has(element.localName)) return null
  const attrs: Record<string, unknown> = {}
  for (const attr of element.attributes) if (mathAttrs.has(attr.name)) attrs[attr.name] = attr.value
  const styles: Record<string, string> = {}
  const style = (element as HTMLElement).style
  if (style) for (const property of style) {
    const value = style.getPropertyValue(property)
    if (lengthStyles.has(property) && /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:em|ex|px|pt|%)?$/.test(value)) styles[property] = value
    if ((property === 'color' || property === 'background-color') && /^(?:#[\da-f]{3,8}|[a-z]+|rgba?\([\d.,%\s]+\))$/i.test(value)) styles[property] = value
    if (property === 'position' && value === 'relative') styles[property] = value
  }
  attrs.style = styles
  return h(element.localName, attrs, Array.from(element.childNodes, mathNode))
}

export function renderMath(content: string, display: boolean, markup: string, block = false): VNodeChild {
  const close = markup === '\\[' ? '\\]' : markup === '\\(' ? '\\)' : markup
  const fallback = () => h(block ? 'div' : 'span', { class: 'math-fallback' }, `${markup}${content}${close}`)
  if (content.length > MAX_FORMULA_LENGTH) return fallback()
  // Bound nesting as well as expansion to avoid pathological parser recursion.
  let depth = 0
  for (const char of content) {
    if (char === '{' && ++depth > 100) return fallback()
    if (char === '}') depth--
  }
  try {
    const html = katex.renderToString(content, {
      displayMode: display, output: 'htmlAndMathml', trust: false, strict: 'error',
      throwOnError: true, maxExpand: 200, maxSize: 20, macros: {},
    })
    const document = new DOMParser().parseFromString(html, 'text/html')
    return h(block ? 'div' : 'span', { class: display ? 'answer-math math-display' : 'answer-math math-inline' }, Array.from(document.body.childNodes, mathNode))
  } catch {
    // Never insert KaTeX error messages (which may contain unescaped input).
    return fallback()
  }
}
