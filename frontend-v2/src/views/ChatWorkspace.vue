<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'
import KnowledgeBasePicker from '@/components/KnowledgeBasePicker.vue'
import AnswerView from '@/components/AnswerView.vue'

const chat = useChatStore(), kb = useKnowledgeBaseStore(), auth = useAuthStore()
const leaving = ref(false)
const query = ref(''), drawer = ref(false), stream = ref<HTMLElement>(), nearBottom = ref(true)
const renaming = ref<string | null>(null), title = ref(''), notice = ref('')
const examples = ['栈和队列有什么区别？', '用一个例子解释 AVL 树的旋转', '如何分析图遍历算法的时间复杂度？', '比较快速排序与归并排序']
const activeTitle = computed(() => chat.items.find(c => c.id === chat.active)?.title ?? '新对话')
const canSend = computed(() => !!query.value.trim() && kb.selectedCount > 0 && !chat.sending && !chat.loading && !chat.pending)
onMounted(async () => { try { await Promise.all([chat.list(), kb.load()]); if (kb.items.length === 1 && !kb.selectedCount) kb.selectedIds = [kb.items[0]!.id]; const saved = new URL(window.location.href).searchParams.get('conversation'); if (saved) await open(saved) } catch { notice.value = '对话列表加载失败，请刷新重试。' } })
watch(() => chat.active, id => { const url = new URL(window.location.href); if (id) url.searchParams.set('conversation', id); else url.searchParams.delete('conversation'); window.history.replaceState(null, '', url) })
function onScroll() { const el = stream.value; if (el) nearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 100 }
async function bottom(force = false) { await nextTick(); if (force || nearBottom.value) stream.value?.scrollTo({top: stream.value.scrollHeight, behavior: 'smooth'}) }
watch(() => [chat.messages.length, chat.sending], () => { void bottom() })
async function send() { if (!canSend.value) return; const text = query.value; query.value = ''; nearBottom.value = true; await chat.send(text, [...kb.selectedIds]); await bottom() }
async function retry() { if (chat.pending) { nearBottom.value = true; await chat.send(chat.pending.payload.query, chat.pending.payload.knowledge_base_ids); await bottom() } }
function keydown(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); void send() } }
function resize(e: Event) { const el = e.target as HTMLTextAreaElement; el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 180)}px` }
async function open(id: string) { drawer.value = false; await chat.open(id); await bottom(true) }
async function rename(id: string) { if (!title.value.trim()) return; try { await chat.rename(id, title.value.trim()); renaming.value = null } catch { notice.value = '重命名失败，请重试。' } }
async function remove(id: string) { if (!window.confirm('删除此对话？此操作会隐藏其全部消息。')) return; try { await chat.remove(id) } catch { notice.value = '删除失败，请重试。' } }
async function copy(text: string) { try { await navigator.clipboard.writeText(text); notice.value = '回答已复制' } catch { notice.value = '浏览器未允许复制，请手动选择文本。' } }
async function logout() { if (leaving.value) return; leaving.value = true; try { if (await logoutAndReset() === 'failed') auth.logoutFailed = true } finally { leaving.value = false } }
async function older() { const el = stream.value; const height = el?.scrollHeight ?? 0; await chat.moreMessages(); await nextTick(); if (el) el.scrollTop += el.scrollHeight - height }
</script>

<template>
  <div class="workspace">
    <button v-if="drawer" class="shade" aria-label="关闭导航" @click="drawer = false"></button>
    <aside class="sidebar" :class="{ visible: drawer }" aria-label="对话导航">
      <a class="brand" href="/">知序 <span>数据结构 AI 助教</span></a>
      <button class="new-chat" :disabled="chat.sending" @click="chat.newChat(); drawer = false">＋ 新建对话</button>
      <div class="history">
        <p class="eyebrow">历史对话</p>
        <p v-if="!chat.items.length" class="muted">从一个问题开始，记录会保存在这里。</p>
        <div v-for="item in chat.items" :key="item.id" class="history-row" :class="{active: item.id === chat.active}">
          <form v-if="renaming === item.id" @submit.prevent="rename(item.id)"><input v-model="title" aria-label="对话标题" maxlength="200" /><button>保存</button><button type="button" @click="renaming = null">取消</button></form>
          <template v-else>
            <button class="history-title" :disabled="chat.sending" @click="open(item.id)">{{ item.title }}</button>
            <details><summary aria-label="对话操作">···</summary><div class="history-actions"><button :disabled="chat.sending" @click="renaming = item.id; title = item.title">重命名</button><button :disabled="chat.sending" @click="remove(item.id)">删除</button></div></details>
          </template>
        </div>
        <button v-if="chat.items.length < chat.total" @click="chat.list(true).catch(() => notice = '加载失败')">更多对话</button>
      </div>
      <details class="knowledge" open><summary>课程知识库</summary><KnowledgeBasePicker /></details>
      <div class="account"><span class="avatar">{{ auth.email.slice(0, 1).toUpperCase() }}</span><span class="email">{{ auth.email }}</span><button :disabled="leaving" @click="logout">{{ leaving ? '退出中…' : '退出' }}</button></div>
    </aside>
    <main class="main">
      <header class="topbar"><button class="menu" aria-label="打开导航" @click="drawer = true">☰</button><span>{{ activeTitle }}</span><span class="single-turn">基于课程证据 · 单轮问答</span></header>
      <div ref="stream" class="stream" @scroll="onScroll">
        <div v-if="!chat.messages.length && !chat.pending && !chat.loading" class="welcome">
          <div class="mark">知</div><h1>把知识连成思路</h1><p>从课程资料出发，一起理解数据结构。</p>
          <div class="examples"><button v-for="example in examples" :key="example" @click="query = example">{{ example }} <span>↗</span></button></div>
        </div>
        <div class="messages">
          <button v-if="chat.messages.length < chat.messageTotal" :disabled="chat.loading" @click="older">加载更早消息</button>
          <article v-for="message in chat.messages" :key="message.id" :class="['message', message.role]">
            <p v-if="message.role === 'user'" class="user-bubble">{{ message.content }}</p>
            <template v-else><div class="assistant-name">知序 · AI 助教</div>
              <AnswerView v-if="message.metadata_json.result" :phase="message.metadata_json.result.status === 'answered' ? 'answered' : 'refused'" :result="message.metadata_json.result" :error-code="null" :error-status="0" error-message="" />
              <p v-else>{{ message.content }}</p>
              <button class="copy" @click="copy(message.content)">复制回答</button>
            </template>
          </article>
          <article v-if="chat.pending" class="message user"><p class="user-bubble">{{ chat.pending.payload.query }}</p></article>
          <div v-if="chat.sending" class="thinking" role="status"><span></span> 正在查阅课程资料，整理回答…</div>
          <p v-if="chat.loading" class="muted" role="status">正在读取历史记录…</p>
          <div v-if="chat.error" class="error" role="alert">{{ chat.error }} <button v-if="chat.pending && !chat.sending" @click="retry">重试</button></div>
        </div>
      </div>
      <div class="composer-wrap">
        <p v-if="notice" class="notice" role="status">{{ notice }} <button aria-label="关闭提示" @click="notice = ''">×</button></p>
        <form class="composer" @submit.prevent="send">
          <textarea v-model="query" aria-label="向 AI 助教提问" placeholder="提出你的数据结构问题…" rows="1" maxlength="2000" :disabled="chat.sending || !!chat.pending" @keydown="keydown" @input="resize"></textarea>
          <button class="send" :disabled="!canSend" aria-label="发送问题">↑</button>
        </form>
        <p class="composer-note">{{ kb.selectedCount ? `已选择 ${kb.selectedCount} 个知识库` : '请先选择课程知识库' }} · 回答可能有误，请核对来源。<span>Enter 发送 · Shift + Enter 换行</span></p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.workspace{display:flex;height:100dvh;overflow:hidden;background:#fff;color:#23332f}.sidebar{width:272px;flex-shrink:0;background:#f3f5f2;border-right:1px solid #e8ece7;padding:26px 16px 14px;display:flex;flex-direction:column;gap:22px}.brand{text-decoration:none;color:#245748;font-size:25px;font-weight:750;letter-spacing:-1px;padding:0 10px}.brand span{display:block;font-size:11px;font-weight:500;letter-spacing:1px;color:#75837c;margin-top:2px}.new-chat{background:#fff;border:1px solid #dce4dc;border-radius:10px;padding:12px;text-align:left;color:#285a48;font-weight:600}.history{flex:1;min-height:100px;overflow:auto}.eyebrow{font-size:11px;color:#88958d;letter-spacing:2px;padding:0 10px}.muted{font-size:13px;color:#829087;padding:0 10px}.history-row{display:flex;align-items:center;border-radius:8px;position:relative}.history-row.active{background:#e2eae1}.history-title{flex:1;min-width:0;text-overflow:ellipsis;white-space:nowrap;overflow:hidden;text-align:left;padding:11px 10px}.history-row details{padding:8px}.history-row summary{cursor:pointer}.history-actions{position:absolute;right:0;background:#fff;box-shadow:0 4px 20px #1232;padding:8px;z-index:5;border-radius:8px}.history-row form{display:flex;flex-wrap:wrap;gap:4px;padding:6px;min-width:0}.history-row input{width:100%;min-width:0}.knowledge{max-height:36vh;overflow:auto;border-top:1px solid #dfe6dc;padding-top:14px}.knowledge>summary{font-size:13px;font-weight:600;cursor:pointer;margin-bottom:14px}.account{display:flex;align-items:center;gap:9px;font-size:12px;border-top:1px solid #dfe6dc;padding-top:14px}.avatar{background:#dce6d9;border-radius:50%;width:30px;height:30px;display:grid;place-items:center;color:#35634b}.email{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis}.main{flex:1;min-width:0;display:flex;flex-direction:column}.topbar{height:66px;flex-shrink:0;display:flex;align-items:center;gap:14px;padding:0 30px;font-size:13px;color:#66766c;border-bottom:1px solid #f1f3ef}.topbar>span:first-of-type{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.single-turn{margin-left:auto;font-size:11px;color:#9aa59d;white-space:nowrap}.menu{display:none}.stream{flex:1;overflow:auto;overscroll-behavior:contain;padding:16px 28px 32px;scrollbar-gutter:stable}.welcome{max-width:710px;margin:clamp(30px,10vh,140px) auto 20px;text-align:center}.mark{width:48px;height:48px;background:#e5eee2;color:#386f50;border-radius:15px;display:grid;place-items:center;font-size:22px;margin:0 auto 20px}.welcome h1{font-size:32px;letter-spacing:-1px;font-weight:650;margin:0 0 10px}.welcome p{color:#87928a;font-size:14px}.examples{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:34px auto 0;max-width:610px}.examples button{border:1px solid #e6ebe3;border-radius:12px;text-align:left;padding:17px;font-size:13px;display:flex;justify-content:space-between;gap:10px;background:#fafbf8}.examples span{color:#8c9f86}.messages{max-width:760px;margin:0 auto}.message{margin:30px 0;min-width:0}.message.user{display:flex;justify-content:flex-end}.user-bubble{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf2e9;padding:12px 18px;border-radius:18px 18px 4px 18px;max-width:85%;margin:0;font-size:15px}.assistant-name{font-size:12px;font-weight:650;color:#598065;margin-bottom:12px}.copy{font-size:11px;color:#909c93;padding:8px 0}.thinking{padding:14px 0;color:#7c8d7d;font-size:13px}.thinking span{display:inline-block;width:8px;height:8px;background:#72996b;border-radius:50%;animation:pulse 1.4s infinite}.error{background:#fff4eb;color:#92522d;padding:14px;border-radius:10px;font-size:13px}.error button{text-decoration:underline}.composer-wrap{padding:10px 28px 20px;background:linear-gradient(#fff9,#fff 20%);flex-shrink:0}.composer{max-width:760px;margin:0 auto;border:1px solid #dfe6dc;border-radius:22px;padding:14px 14px 14px 20px;display:flex;align-items:flex-end;gap:12px;box-shadow:0 4px 24px #23332f06;background:#fafbf9}.composer:focus-within{border-color:#9eb49a}.composer textarea{flex:1;min-width:0;resize:none;border:0;outline:0;background:transparent;line-height:1.7;max-height:180px;font-size:15px;padding:3px 0}.send{width:36px;height:36px;flex-shrink:0;border-radius:50%;background:#326448;color:white;font-size:22px}.send:disabled{background:#dfe6dc;color:#9baa98}.composer-note{max-width:760px;margin:9px auto 0;text-align:center;font-size:10px;color:#96a092}.composer-note span{margin-left:12px}.notice{text-align:center;font-size:12px;color:#637e5d}.shade{display:none}button{border:0;background:transparent;cursor:pointer}button:disabled{cursor:not-allowed;opacity:.55}@keyframes pulse{50%{opacity:.3}}@media(max-width:760px){.sidebar{position:fixed;inset:0 auto 0 0;z-index:30;transform:translateX(-100%);visibility:hidden;width:280px;max-width:85vw}.sidebar.visible{transform:translateX(0);visibility:visible}.shade{display:block;position:fixed;inset:0;background:#172b2355;z-index:25}.menu{display:block;font-size:20px}.topbar{height:56px;padding:0 16px}.single-turn{display:none}.stream{padding:12px 18px 24px}.welcome{margin-top:45px}.welcome h1{font-size:27px}.examples{grid-template-columns:1fr;gap:8px;margin-top:26px}.examples button{padding:14px}.composer-wrap{padding:8px 12px max(12px,env(safe-area-inset-bottom))}.composer-note span{display:none}.message{margin:24px 0}.user-bubble{max-width:92%}.composer{border-radius:20px;padding-left:16px}}
</style>
