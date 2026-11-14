<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'
import KnowledgeBasePicker from '@/components/KnowledgeBasePicker.vue'
import AnswerView from '@/components/AnswerView.vue'
import AnswerText from '@/components/AnswerText.vue'
import CopyAnswerButton from '@/components/CopyAnswerButton.vue'

const chat = useChatStore(), kb = useKnowledgeBaseStore(), auth = useAuthStore()
const leaving = ref(false)
const query = ref(''), drawer = ref(false), stream = ref<HTMLElement>(), nearBottom = ref(true)
const renaming = ref<string | null>(null), title = ref(''), notice = ref('')
const examples = ['栈和队列有什么区别？', '用一个例子解释 AVL 树的旋转', '如何分析图遍历算法的时间复杂度？', '比较快速排序与归并排序']
const activeTitle = computed(() => chat.items.find(c => c.id === chat.active)?.title ?? '新对话')
const canSend = computed(() => !!query.value.trim() && kb.courseSelected && !chat.sending && !chat.loading && !chat.pending)
watch(() => kb.course?.id, () => { if (chat.sending) chat.cancel(); kb.selectCourse() }, { immediate: true })
onMounted(async () => { try { await Promise.all([chat.list(), kb.load()]); const saved = new URL(window.location.href).searchParams.get('conversation'); if (saved) await open(saved) } catch { notice.value = '对话列表加载失败，请刷新重试。' } })
watch(() => chat.active, id => { const url = new URL(window.location.href); if (id) url.searchParams.set('conversation', id); else url.searchParams.delete('conversation'); window.history.replaceState(null, '', url) })
function onScroll() { const el = stream.value; if (el) nearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 100 }
async function bottom(force = false) { await nextTick(); if (force || nearBottom.value) stream.value?.scrollTo({top: stream.value.scrollHeight, behavior: 'smooth'}) }
watch(() => [chat.messages.length, chat.sending, chat.draft.length, chat.streamStage], () => { void bottom() })
const progress = computed(() => ({accepted:'正在发送问题…',retrieving:'正在检索课程资料…',generating:'正在生成回答…',validating:'正在校验回答与资料来源…',saving:'正在保存已校验的回答…',completed:'回答已完成',failed:'回答未完成',cancelled:'已停止生成'}[chat.streamStage ?? 'accepted']))
async function send() { if (!canSend.value) return; const text = query.value; query.value = ''; nearBottom.value = true; await chat.send(text, [...kb.selectedIds]); await bottom() }
async function retry() { if (chat.pending) {
  const ids = chat.pending.payload.knowledge_base_ids
  if (!kb.courseSelected || ids.length !== 1 || ids[0] !== kb.course?.id) { notice.value = '待重试问题属于其他知识库，请新建对话；不会自动更换原问题的资料范围。'; return }
  nearBottom.value = true; await chat.send(chat.pending.payload.query, ids); await bottom()
} }
function keydown(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); void send() } }
function resize(e: Event) { const el = e.target as HTMLTextAreaElement; el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 180)}px` }
async function open(id: string) { drawer.value = false; await chat.open(id); await bottom(true) }
async function rename(id: string) { if (!title.value.trim()) return; try { await chat.rename(id, title.value.trim()); renaming.value = null } catch { notice.value = '重命名失败，请重试。' } }
async function remove(id: string) { if (!window.confirm('删除此对话？此操作会隐藏其全部消息。')) return; try { await chat.remove(id) } catch { notice.value = '删除失败，请重试。' } }
async function logout() { if (leaving.value) return; leaving.value = true; try { if (await logoutAndReset() === 'failed') auth.logoutFailed = true } finally { leaving.value = false } }
async function older() { const el = stream.value; const height = el?.scrollHeight ?? 0; await chat.moreMessages(); await nextTick(); if (el) el.scrollTop += el.scrollHeight - height }
</script>

<template>
  <div class="workspace">
    <button v-if="drawer" class="shade" aria-label="关闭导航" @click="drawer = false"></button>
    <aside class="sidebar" :class="{ visible: drawer }" aria-label="对话导航">
      <a class="brand" href="/">数据结构 AI 助教</a>
      <button class="new-chat" @click="chat.newChat(); drawer = false">＋ 新建对话</button>
      <section class="knowledge" aria-label="课程知识库"><KnowledgeBasePicker /></section>
      <div class="history">
        <p class="eyebrow">历史对话</p>
        <div class="history-list">
        <p v-if="!chat.items.length" class="muted">从一个问题开始，记录会保存在这里。</p>
        <div v-for="item in chat.items" :key="item.id" class="history-row" :class="{active: item.id === chat.active}">
          <form v-if="renaming === item.id" @submit.prevent="rename(item.id)"><input v-model="title" aria-label="对话标题" maxlength="200" /><button>保存</button><button type="button" @click="renaming = null">取消</button></form>
          <template v-else>
            <button class="history-title" @click="open(item.id)">{{ item.title }}</button>
            <details><summary aria-label="对话操作">···</summary><div class="history-actions"><button :disabled="chat.sending" @click="renaming = item.id; title = item.title">重命名</button><button :disabled="chat.sending" @click="remove(item.id)">删除</button></div></details>
          </template>
        </div>
        <button v-if="chat.items.length < chat.total" @click="chat.list(true).catch(() => notice = '加载失败')">更多对话</button>
        </div>
      </div>
      <div class="account"><span class="avatar">{{ auth.email.slice(0, 1).toUpperCase() }}</span><span class="email">{{ auth.email }}</span><button :disabled="leaving" @click="logout">{{ leaving ? '退出中…' : '退出' }}</button></div>
    </aside>
    <main class="main">
      <header class="topbar"><button class="menu" aria-label="打开导航" @click="drawer = true">☰</button><span>{{ activeTitle }}</span><span class="single-turn">基于课程证据 · 近期对话上下文</span></header>
      <div ref="stream" class="stream" @scroll="onScroll">
        <div v-if="!chat.messages.length && !chat.pending && !chat.loading" class="welcome">
          <h1>把知识连成思路</h1><p>从课程资料出发，一起理解数据结构。</p>
          <div class="examples"><button v-for="example in examples" :key="example" @click="query = example">{{ example }} <span>↗</span></button></div>
        </div>
        <div class="messages">
          <button v-if="chat.messages.length < chat.messageTotal" :disabled="chat.loading" @click="older">加载更早消息</button>
          <article v-for="message in chat.messages" :key="message.id" :class="['message', message.role]">
            <p v-if="message.role === 'user'" class="user-bubble">{{ message.content }}</p>
            <template v-else><div class="assistant-name">AI 助教</div>
              <AnswerView v-if="message.metadata_json.result" :phase="message.metadata_json.result.status === 'answered' ? 'answered' : 'refused'" :result="message.metadata_json.result" :error-code="null" :error-status="0" error-message="">
                <template #answer-actions><CopyAnswerButton :text="message.metadata_json.result.answer ?? message.content" /></template>
              </AnswerView>
              <template v-else><p>{{ message.content }}</p><CopyAnswerButton :text="message.content" /></template>
            </template>
          </article>
          <article v-if="chat.pending" class="message user"><p class="user-bubble">{{ chat.pending.payload.query }}</p></article>
          <div v-if="chat.sending" class="thinking" role="status"><span></span> {{ progress }}</div>
          <section v-if="chat.sending && chat.draft" class="stream-draft" aria-label="临时草稿，尚未校验" @copy.prevent>
            <p class="draft-label">生成草稿 · 尚未校验，完成后可能修正或撤回</p>
            <div class="draft-text"><AnswerText :text="chat.draft" :sources="[]" preview /></div>
          </section>
          <p v-if="chat.loading" class="muted" role="status">正在读取历史记录…</p>
          <div v-if="chat.error" class="error" role="alert">{{ chat.error }} <button v-if="chat.pending && !chat.sending" @click="retry">重试</button></div>
        </div>
      </div>
      <div class="composer-wrap">
        <p v-if="!kb.loading && (kb.courseIssue || kb.errorCode)" class="course-warning" role="alert">{{ kb.courseIssue || '课程资料加载失败，请在导航中重新加载或联系管理员。' }}</p>
        <p v-if="notice" class="notice" role="status">{{ notice }} <button aria-label="关闭提示" @click="notice = ''">×</button></p>
        <form class="composer" @submit.prevent="send">
          <textarea v-model="query" aria-label="向 AI 助教提问" placeholder="提出你的数据结构问题…" rows="1" maxlength="2000" :disabled="chat.sending || !!chat.pending" @keydown="keydown" @input="resize"></textarea>
          <button v-if="chat.sending" type="button" class="stop" aria-label="停止生成" @click="chat.cancel()">■</button>
          <button v-else class="send" :disabled="!canSend" aria-label="发送问题">↑</button>
        </form>
        <p class="composer-note">回答可能有误，请核对资料来源。<span>Enter 发送 · Shift + Enter 换行</span></p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.workspace {
  --ink: #171717;
  --muted: #737373;
  --line: #ebebeb;
  --brand: #262626;
  display: flex;
  height: 100dvh;
  overflow: hidden;
  background: #FFFFFF;
  color: var(--ink);
}
.sidebar {
  width: 272px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 26px 16px 14px;
  background: #FFFFFF;
  border-right: 1px solid var(--line);
}
.brand { padding: 0 10px; color: var(--ink); font-size: 17px; font-weight: 650; text-decoration: none; }
.new-chat { padding: 11px 12px; border: 1px solid #e5e5e5; border-radius: 10px; text-align: left; font-weight: 550; }
.new-chat:hover { background: #f5f5f5; }
.knowledge { flex-shrink: 0; max-height: 30vh; overflow-y: auto; }
.history { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.history-list { flex: 1; min-height: 0; overflow-y: auto; }
.eyebrow { margin: 0 10px 8px; font-size: 12px; color: var(--muted); }
.muted { padding: 0 10px; font-size: 13px; color: var(--muted); }
.history-row { display: flex; align-items: center; border-radius: 8px; position: relative; }
.history-row:hover { background: #fafafa; }
.history-row.active { background: #f1f1f1; }
.history-title { flex: 1; min-width: 0; padding: 11px 10px; text-overflow: ellipsis; white-space: nowrap; overflow: hidden; text-align: left; }
.history-row details { padding: 8px; }
.history-row summary { cursor: pointer; list-style: none; }
.history-row summary::-webkit-details-marker { display: none; }
.history-actions { position: absolute; right: 0; z-index: 5; padding: 8px; border: 1px solid #e5e5e5; border-radius: 8px; background: #FFFFFF; }
.history-actions button { display: block; padding: 6px 12px; white-space: nowrap; }
.history-actions button:hover { background: #f5f5f5; }
.history-row form { display: flex; flex-wrap: wrap; gap: 4px; min-width: 0; padding: 6px; }
.history-row input { width: 100%; min-width: 0; }
.account { display: flex; flex-shrink: 0; align-items: center; gap: 9px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 12px; }
.avatar { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; background: #f1f1f1; color: #525252; }
.email { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar { display: flex; flex-shrink: 0; align-items: center; gap: 14px; height: 66px; padding: 0 30px; font-size: 13px; color: #737373; }
.topbar>span:first-of-type { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.single-turn { margin-left: auto; font-size: 11px; color: #909090; white-space: nowrap; }
.menu { display: none; }
.stream { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 16px 28px 32px; scrollbar-gutter: stable; }
.welcome { max-width: 710px; margin: clamp(30px, 15vh, 140px) auto 20px; text-align: center; }
.welcome h1 { margin: 0 0 10px; font-size: 32px; letter-spacing: -1px; font-weight: 650; }
.welcome p { color: #737373; font-size: 14px; }
.examples { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 610px; margin: 34px auto 0; }
.examples button { display: flex; justify-content: space-between; gap: 10px; padding: 17px; border: 1px solid #ededed; border-radius: 12px; text-align: left; font-size: 13px; }
.examples button:hover { background: #f7f7f7; }
.examples span { color: #8a8a8a; }
.messages { max-width: 760px; margin: 0 auto; }
.message { margin: 30px 0; min-width: 0; }
.message.user { display: flex; justify-content: flex-end; }
.user-bubble { max-width: 85%; margin: 0; padding: 12px 18px; border-radius: 18px 18px 4px 18px; background: #f3f3f3; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 15px; }
.assistant-name { margin-bottom: 12px; color: #525252; font-size: 12px; font-weight: 600; }
.thinking { padding: 14px 0; color: #737373; font-size: 13px; }
.thinking span { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #737373; animation: pulse 1.4s infinite; }
.error { padding: 14px; border-radius: 10px; background: #f5f5f5; color: #404040; font-size: 13px; }
.error button { text-decoration: underline; }
.composer-wrap { flex-shrink: 0; padding: 10px 28px 20px; background: #FFFFFF; }
.composer { display: flex; align-items: flex-end; gap: 12px; max-width: 760px; margin: 0 auto; padding: 14px 14px 14px 20px; border: 1px solid #dedede; border-radius: 22px; background: #FFFFFF; }
.composer:focus-within { border-color: #a3a3a3; }
.composer textarea { flex: 1; min-width: 0; max-height: 180px; padding: 3px 0; border: 0; outline: 0; resize: none; background: transparent; line-height: 1.7; font-size: 15px; }
.send { width: 36px; height: 36px; flex-shrink: 0; border-radius: 50%; background: #2563EB; color: #FFFFFF; font-size: 22px; }
.send:disabled { background: #e5e5e5; color: #a3a3a3; opacity: 1; }
.stop { width: 36px; height: 36px; flex-shrink: 0; border-radius: 50%; background: #262626; color: #fff; }
.stream-draft { margin: 12px 0 24px; min-width: 0; max-width: 100%; }
.draft-label { font-size: 12px; color: #737373; margin: 0 0 10px; }
.draft-text { overflow-wrap: anywhere; line-height: 1.8; font-size: 15px; }
.draft-text :deep(.answer-text) { color: #525252; }
.composer-note { max-width: 760px; margin: 9px auto 0; text-align: center; font-size: 10px; color: #858585; }
.composer-note span { margin-left: 12px; }
.notice { text-align: center; font-size: 12px; color: #525252; }
.course-warning { max-width: 760px; margin: 0 auto 8px; color: #525252; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.shade { display: none; }
button { border: 0; background: transparent; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .55; }
@keyframes pulse { 50% { opacity: .3; } }
@media (max-width: 760px) {
  .sidebar { position: fixed; inset: 0 auto 0 0; z-index: 30; transform: translateX(-100%); visibility: hidden; width: 280px; max-width: 85vw; gap: 18px; }
  .sidebar.visible { transform: translateX(0); visibility: visible; }
  .shade { display: block; position: fixed; inset: 0; z-index: 25; background: #00000045; }
  .menu { display: block; font-size: 20px; }
  .topbar { height: 56px; padding: 0 16px; }
  .single-turn { display: none; }
  .stream { padding: 12px 18px 24px; }
  .welcome { margin-top: 45px; }
  .welcome h1 { font-size: 27px; }
  .examples { grid-template-columns: 1fr; gap: 8px; margin-top: 26px; }
  .examples button { padding: 14px; }
  .composer-wrap { padding: 8px 12px max(12px, env(safe-area-inset-bottom)); }
  .composer-note span { display: none; }
  .message { margin: 24px 0; }
  .user-bubble { max-width: 92%; }
  .composer { border-radius: 20px; padding-left: 16px; }
}
</style>
