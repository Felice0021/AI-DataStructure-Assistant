<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useKnowledgeBaseStore } from '@/stores/knowledgeBase'
import { useAuthStore } from '@/stores/auth'
import { logoutAndReset } from '@/stores/reset'
import KnowledgeBasePicker from '@/components/KnowledgeBasePicker.vue'
import AnswerView from '@/components/AnswerView.vue'
import AnswerText from '@/components/AnswerText.vue'
import CopyAnswerButton from '@/components/CopyAnswerButton.vue'
import type { StudyMemory } from '@/api/projects'

const chat = useChatStore(), kb = useKnowledgeBaseStore(), auth = useAuthStore()
const leaving = ref(false)
const query = ref(''), drawer = ref(false), stream = ref<HTMLElement>(), nearBottom = ref(true)
const renaming = ref<string | null>(null), title = ref(''), notice = ref('')
const openActions = ref<string | null>(null), historyExpanded = ref(true), projectsExpanded = ref(true)
const expandedProjects = ref<Record<string, boolean>>({})
const creatingProject = ref(false), projectName = ref(''), projectDescription = ref('')
const editingProject = ref<string | null>(null), editName = ref(''), editDescription = ref('')
const editSources = ref<string[]>([]), projectMemories = ref<StudyMemory[]>([]), memoryLoading = ref(false)
const moving = ref<string | null>(null), destination = ref('')
watch(editingProject, id => { if (!id) { projectMemories.value = []; editSources.value = []; editName.value = ''; editDescription.value = '' } })
const examples = ['栈和队列有什么区别？', '用一个例子解释 AVL 树的旋转', '如何分析图遍历算法的时间复杂度？', '比较快速排序与归并排序']
const activeTitle = computed(() => chat.items.find(c => c.id === chat.active)?.title ?? '新对话')
const activeProjectTitle = computed(() => chat.projects.find(p => p.id === chat.activeProject)?.title ?? '')
const ordinaryConversations = computed(() => chat.items.filter(item => !item.project_id || !chat.projects.some(p => p.id === item.project_id)))
function projectConversations(id: string) { return chat.items.filter(item => item.project_id === id) }
const sidebarGroups = computed(() => [
  ...chat.projects.map(project => ({id: project.id, project, items: projectConversations(project.id)})),
  {id: 'ordinary', project: null, items: ordinaryConversations.value},
])
const canSend = computed(() => !!query.value.trim() && kb.courseSelected && !chat.sending && !chat.loading && !chat.pending)
watch(() => kb.course?.id, () => { if (chat.sending) chat.cancel(); kb.selectCourse() }, { immediate: true })
function closeActionsOutside(event: MouseEvent) {
  if (!(event.target instanceof Element) || !event.target.closest('.history-operations')) openActions.value = null
}
function closeActionsOnEscape(event: KeyboardEvent) { if (event.key === 'Escape') { openActions.value = null; editingProject.value = null } }
onMounted(async () => {
  document.addEventListener('click', closeActionsOutside)
  document.addEventListener('keydown', closeActionsOnEscape)
  try { await Promise.all([chat.list(), chat.listProjects(), kb.load()]); const saved = new URL(window.location.href).searchParams.get('conversation'); if (saved) await open(saved) } catch { notice.value = '对话列表加载失败，请刷新重试。' }
})
onUnmounted(() => {
  document.removeEventListener('click', closeActionsOutside)
  document.removeEventListener('keydown', closeActionsOnEscape)
})
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
async function open(id: string) {
  drawer.value = false; openActions.value = null; nearBottom.value = false
  await chat.open(id)
  await nextTick()
  if (chat.active === id) {
    // History must appear at its latest message without animating through the entire transcript.
    stream.value?.scrollTo({ top: stream.value.scrollHeight, behavior: 'instant' })
    nearBottom.value = true
  }
}
function newChat(projectId: string | null = null) { openActions.value = null; drawer.value = false; nearBottom.value = true; chat.selectProject(projectId) }
function toggleProjectCreation() {
  if (!projectsExpanded.value) { projectsExpanded.value = true; creatingProject.value = true }
  else creatingProject.value = !creatingProject.value
}
async function addProject() {
  if (!projectName.value.trim()) return
  try {
    const created = await chat.createProject(projectName.value.trim(), projectDescription.value.trim())
    if (created) { expandedProjects.value[created.id] = true; projectsExpanded.value = true }
    projectName.value = ''; projectDescription.value = ''; creatingProject.value = false; drawer.value = false
  } catch { notice.value = '项目创建失败，请检查名称或稍后重试。' }
}
async function editProject(id: string) {
  const project = chat.projects.find(item => item.id === id)
  if (!project) return
  editingProject.value = id; editName.value = project.title; editDescription.value = project.description
  editSources.value = [...project.memory_source_ids]; projectMemories.value = []; memoryLoading.value = true
  try { const notes = await chat.projectMemories(id); if (editingProject.value === id) projectMemories.value = notes }
  catch { notice.value = '学习记忆加载失败。' }
  finally { if (editingProject.value === id) memoryLoading.value = false }
}
async function saveProject() {
  if (!editingProject.value || !editName.value.trim()) return
  try { await chat.updateProject(editingProject.value, {title: editName.value.trim(), description: editDescription.value.trim(), memory_source_ids: [...editSources.value]}); editingProject.value = null }
  catch { notice.value = '项目设置保存失败，请重试。' }
}
async function deleteProject(id: string) {
  if (!window.confirm('删除此项目？项目内的聊天将保留并移回普通历史，但项目学习记忆会被清除。')) return
  try { await chat.deleteProject(id); editingProject.value = null }
  catch { notice.value = '项目删除失败，请重试。' }
}
async function forgetMemory(id: string, noteId: string) {
  try { await chat.forgetMemory(id, noteId); projectMemories.value = projectMemories.value.filter(note => note.id !== noteId) }
  catch { notice.value = '删除学习记忆失败，请重试。' }
}
async function moveConversation(id: string) {
  try { await chat.moveConversation(id, destination.value || null); moving.value = null }
  catch { notice.value = '移动对话失败，请重试。' }
}
function toggleHistory() { historyExpanded.value = !historyExpanded.value; openActions.value = null }
function toggleActions(id: string) { openActions.value = openActions.value === id ? null : id }
async function rename(id: string) { if (!title.value.trim()) return; try { await chat.rename(id, title.value.trim()); renaming.value = null; openActions.value = null } catch { notice.value = '重命名失败，请重试。' } }
async function remove(id: string) { openActions.value = null; if (!window.confirm('删除此对话？此操作会隐藏其全部消息。')) return; try { await chat.remove(id) } catch { notice.value = '删除失败，请重试。' } }
async function logout() { if (leaving.value) return; leaving.value = true; try { if (await logoutAndReset() === 'failed') auth.logoutFailed = true } finally { leaving.value = false } }
async function older() { const el = stream.value; const height = el?.scrollHeight ?? 0; await chat.moreMessages(); await nextTick(); if (el) el.scrollTop += el.scrollHeight - height }
</script>

<template>
  <div class="workspace">
    <button v-if="drawer" class="shade" aria-label="关闭导航" @click="drawer = false"></button>
    <aside class="sidebar" :class="{ visible: drawer }" aria-label="对话导航">
      <a class="brand" href="/">数据结构 AI 助教</a>
      <button class="new-chat" @click="newChat()">＋ 新建对话</button>
      <section class="knowledge" aria-label="课程知识库"><KnowledgeBasePicker /></section>
      <div class="history">
        <div class="history-list">
          <div class="project-heading">
            <button class="project-toggle section-toggle eyebrow" type="button" :aria-expanded="projectsExpanded" :aria-controls="chat.projects.map(project => `project-section-${project.id}`).join(' ') || undefined" @click="projectsExpanded = !projectsExpanded">
              <span>项目</span><svg class="fold-chevron" :class="{ collapsed: !projectsExpanded }" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
            </button>
            <button type="button" aria-label="新建项目" :disabled="chat.sending" @click="toggleProjectCreation">＋ 新建项目</button>
          </div>
          <form v-if="creatingProject" v-show="projectsExpanded" class="project-create" @submit.prevent="addProject">
            <input v-model="projectName" aria-label="项目名称" maxlength="100" placeholder="例如：二叉树" required />
            <textarea v-model="projectDescription" aria-label="项目说明" maxlength="500" placeholder="可选：这个项目准备学习什么？" rows="2"></textarea>
            <div><button type="submit">创建</button><button type="button" @click="creatingProject = false">取消</button></div>
          </form>
          <section v-for="group in sidebarGroups" :id="group.project ? `project-section-${group.id}` : undefined" :key="group.id" v-show="!group.project || projectsExpanded" class="conversation-group">
            <div v-if="group.project" class="project-header" :class="{ selected: chat.activeProject === group.id }">
              <button class="project-title" type="button" :title="group.project.title" @click="newChat(group.id)">{{ group.project.title }}</button>
              <button type="button" :aria-label="`在${group.project.title}中新建对话`" :disabled="chat.sending" @click="newChat(group.id)">＋</button>
              <button type="button" :aria-label="`设置项目：${group.project.title}`" :disabled="chat.sending" @click="editProject(group.id)">⚙</button>
              <button type="button" :aria-label="`展开或收起项目：${group.project.title}`" :aria-expanded="expandedProjects[group.id] !== false" :aria-controls="`group-${group.id}`" @click="expandedProjects[group.id] = expandedProjects[group.id] === false">
                <svg class="fold-chevron" :class="{ collapsed: expandedProjects[group.id] === false }" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
              </button>
            </div>
            <button v-else class="history-toggle section-toggle eyebrow" type="button" aria-controls="history-conversations" :aria-expanded="historyExpanded" @click="toggleHistory">
              <span>历史对话</span><svg class="fold-chevron" :class="{ collapsed: !historyExpanded }" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
            </button>
            <div :id="group.project ? `group-${group.id}` : 'history-conversations'" v-show="group.project ? expandedProjects[group.id] !== false : historyExpanded" class="group-conversations">
              <p v-if="!group.items.length && !group.project" class="muted">从一个问题开始，记录会保存在这里。</p>
              <div v-for="item in group.items" :key="item.id" class="history-row" :class="{active: item.id === chat.active, 'actions-open': openActions === item.id}">
                <form v-if="renaming === item.id" @submit.prevent="rename(item.id)"><input v-model="title" aria-label="对话标题" maxlength="200" /><button>保存</button><button type="button" @click="renaming = null">取消</button></form>
                <form v-else-if="moving === item.id" @submit.prevent="moveConversation(item.id)">
                  <select v-model="destination" aria-label="移动到项目"><option value="">普通历史</option><option v-for="project in chat.projects" :key="project.id" :value="project.id">{{ project.title }}</option></select>
                  <button type="submit">保存</button><button type="button" @click="moving = null">取消</button>
                </form>
                <template v-else>
                  <button class="history-title" @click="open(item.id)">{{ item.title }}</button>
                  <div class="history-operations">
                    <button class="history-more" type="button" :aria-label="`对话操作：${item.title}`" :aria-expanded="openActions === item.id" aria-haspopup="menu" @click="toggleActions(item.id)">···</button>
                    <div v-if="openActions === item.id" class="history-actions" role="menu">
                      <button type="button" role="menuitem" :disabled="chat.sending" @click="renaming = item.id; title = item.title; openActions = null">重命名</button>
                      <button type="button" role="menuitem" :disabled="chat.sending" @click="moving = item.id; destination = item.project_id ?? ''; openActions = null">移动到项目</button>
                      <button type="button" role="menuitem" :disabled="chat.sending" @click="remove(item.id)">删除</button>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </section>
          <button v-if="chat.items.length < chat.total" class="more-chats" @click="chat.list(true).catch(() => notice = '加载失败')">更多对话</button>
        </div>
      </div>
      <div class="account"><span class="avatar">{{ auth.email.slice(0, 1).toUpperCase() }}</span><span class="email">{{ auth.email }}</span><button :disabled="leaving" @click="logout">{{ leaving ? '退出中…' : '退出' }}</button></div>
    </aside>
    <main class="main">
      <header class="topbar"><button class="menu" aria-label="打开导航" @click="drawer = true">☰</button><span>{{ activeTitle }}</span><span v-if="activeProjectTitle" class="current-project">{{ activeProjectTitle }}</span><span class="single-turn">基于课程证据 · 近期对话上下文</span></header>
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
    <div v-if="editingProject" class="project-overlay" @click.self="editingProject = null">
      <section class="project-dialog" role="dialog" aria-modal="true" aria-labelledby="project-dialog-heading">
        <div class="project-dialog-header"><h2 id="project-dialog-heading">项目设置</h2><button type="button" aria-label="关闭项目设置" @click="editingProject = null">×</button></div>
        <form @submit.prevent="saveProject">
          <label>项目名称<input v-model="editName" maxlength="100" required /></label>
          <label>学习范围<textarea v-model="editDescription" maxlength="500" rows="2" placeholder="记录该主题的学习目标（可选）"></textarea></label>
          <fieldset class="source-projects">
            <legend>允许读取其他项目的学习记忆</legend>
            <p>默认隔离。仅勾选的项目可以作为当前项目的记忆来源；不会共享原始完整聊天或教材权限。</p>
            <label v-for="other in chat.projects.filter(p => p.id !== editingProject)" :key="other.id" class="source-choice">
              <input v-model="editSources" type="checkbox" :value="other.id" />{{ other.title }}
            </label>
            <p v-if="chat.projects.length <= 1" class="muted">还没有其他项目可供选择。</p>
          </fieldset>
          <div class="project-dialog-actions"><button type="submit" class="primary-action">保存设置</button><button type="button" @click="editingProject = null">取消</button></div>
        </form>
        <div class="memory-panel">
          <h3>本项目的学习记忆</h3>
          <p>自动从已校验回答提取短摘录，仅帮助回忆讨论内容，不代表已经掌握，也不能替代课程证据。</p>
          <p v-if="memoryLoading" class="muted">正在读取…</p>
          <p v-else-if="!projectMemories.length" class="muted">暂无记忆。项目内完成课程问答后会逐步生成。</p>
          <ul v-else><li v-for="memory in projectMemories" :key="memory.id"><span><b>{{ memory.topic }}</b>：{{ memory.summary }}</span><button type="button" :aria-label="`忘记：${memory.topic}`" @click="forgetMemory(editingProject!, memory.id)">删除</button></li></ul>
        </div>
        <button type="button" class="delete-project" @click="deleteProject(editingProject!)">删除项目（保留聊天）</button>
      </section>
    </div>
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
.new-chat { padding: 11px 12px; border: 1px solid #e5e5e5; border-radius: 10px; text-align: left; font-weight: 400; }
.new-chat:hover { background: #f5f5f5; }
.knowledge { flex-shrink: 0; max-height: 30vh; overflow-y: auto; }
.history { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.history-list { flex: 1; min-height: 0; overflow-y: auto; }
.project-heading { display: flex; align-items: center; justify-content: space-between; min-height: 24px; margin: 0 10px 20px; }
.project-heading .eyebrow { margin: 0; }
.project-heading > button:last-child { padding: 0; color: #555; font-size: 12px; }
.section-toggle { display: inline-flex; align-items: center; gap: 8px; min-height: 24px; padding: 0; font-size: 14px; font-weight: 600; line-height: 1.4; color: #525252; text-align: left; }
.project-create { display: grid; gap: 6px; padding: 7px 10px 12px; }
.project-create input, .project-create textarea { width: 100%; min-width: 0; border: 1px solid #dedede; border-radius: 6px; padding: 7px; font: inherit; font-size: 12px; resize: vertical; }
.project-create div { display: flex; gap: 12px; font-size: 12px; }
.project-create div button:first-child { color: #2563eb; }
.conversation-group { margin: 0 0 12px; }
.project-header { display: flex; align-items: center; padding: 4px 5px 4px 10px; border-radius: 8px; }
.project-header:hover, .project-header.selected { background: #f5f5f5; }
.project-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; font-size: 13px; }
.project-header > button:not(.project-title) { padding: 4px 5px; color: #777; font-size: 14px; }
.group-conversations { margin-left: 6px; }
.more-chats { padding: 9px; font-size: 12px; color: #666; }
.eyebrow { margin: 0 10px 8px; }
.history-toggle { flex-shrink: 0; }
.fold-chevron { display: block; width: 16px; height: 16px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; transform-origin: 50% 50%; transition: transform 150ms ease; }
.section-toggle .fold-chevron { width: 14px; height: 14px; stroke-width: 1.25; }
.fold-chevron.collapsed { transform: rotate(-90deg); }
@media (prefers-reduced-motion: reduce) { .fold-chevron { transition: none; } }
.muted { padding: 0 10px; font-size: 13px; color: var(--muted); }
.history-row { display: flex; align-items: center; border-radius: 8px; position: relative; }
.history-row.actions-open { z-index: 6; }
.history-row:hover { background: #fafafa; }
.history-row.active { background: #f1f1f1; }
.history-title { flex: 1; min-width: 0; padding: 11px 10px; text-overflow: ellipsis; white-space: nowrap; overflow: hidden; text-align: left; }
.history-more { padding: 8px; }
.history-actions { position: absolute; top: calc(100% - 2px); right: 0; z-index: 5; padding: 8px; border: 1px solid #e5e5e5; border-radius: 8px; background: #FFFFFF; box-shadow: 0 6px 18px #00000010; }
.history-actions button { display: block; padding: 6px 12px; white-space: nowrap; }
.history-actions button:hover { background: #f5f5f5; }
.history-row form { display: flex; flex-wrap: wrap; gap: 4px; min-width: 0; padding: 6px; }
.history-row input { width: 100%; min-width: 0; }
.history-row select { width: 100%; min-width: 0; border: 1px solid #ddd; border-radius: 5px; padding: 3px; }
.account { display: flex; flex-shrink: 0; align-items: center; gap: 9px; margin-top: auto; padding-top: 14px; border-top: 1px solid var(--line); font-size: 12px; }
.avatar { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; background: #f1f1f1; color: #525252; }
.email { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar { display: flex; flex-shrink: 0; align-items: center; gap: 14px; height: 66px; padding: 0 30px; font-size: 13px; color: #737373; }
.topbar>span:first-of-type { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.single-turn { margin-left: auto; font-size: 11px; color: #909090; white-space: nowrap; }
.current-project { margin-left: 8px; padding: 3px 8px; border-radius: 6px; background: #f3f3f3; font-size: 11px; white-space: nowrap; }
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
.project-overlay { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: #0005; }
.project-dialog { width: min(520px, 100%); max-height: 90dvh; overflow-y: auto; padding: 22px; border-radius: 16px; background: #fff; box-shadow: 0 20px 55px #0002; font-size: 13px; }
.project-dialog-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.project-dialog h2 { margin: 0; font-size: 18px; }
.project-dialog-header button { font-size: 24px; }
.project-dialog form { display: grid; gap: 14px; }
.project-dialog form > label { display: grid; gap: 6px; color: #444; }
.project-dialog input:not([type=checkbox]), .project-dialog textarea { border: 1px solid #ddd; border-radius: 8px; padding: 9px; font: inherit; }
.source-projects { border: 1px solid #eee; border-radius: 8px; padding: 12px; }
.source-projects legend { padding: 0 4px; font-weight: 600; }
.source-projects p, .memory-panel > p { color: #737373; font-size: 12px; line-height: 1.5; }
.source-choice { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.project-dialog-actions { display: flex; align-items: center; gap: 16px; }
.primary-action { border-radius: 7px; padding: 8px 14px; background: #262626; color: #fff; }
.memory-panel { margin-top: 22px; padding-top: 14px; border-top: 1px solid #eee; }
.memory-panel h3 { margin: 0; font-size: 14px; }
.memory-panel ul { padding: 0; list-style: none; }
.memory-panel li { display: flex; align-items: flex-start; gap: 10px; padding: 10px 0; border-bottom: 1px solid #f1f1f1; line-height: 1.6; overflow-wrap: anywhere; }
.memory-panel li span { flex: 1; min-width: 0; }
.memory-panel li button { color: #666; white-space: nowrap; }
.delete-project { margin-top: 16px; color: #b42318; font-size: 12px; }
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
  .project-dialog { padding: 18px; }
  .current-project { max-width: 35vw; overflow: hidden; text-overflow: ellipsis; }
}
</style>
