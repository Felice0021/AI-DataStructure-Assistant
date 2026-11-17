import { defineStore } from 'pinia'
import { conversationsApi, type Conversation, type ChatMessage } from '@/api/conversations'
import { cloudConsentApi, type CloudPurpose } from '@/api/cloudConsent'
import { currentEpoch } from '@/api/session'
import { ApiError } from '@/api/http'
import type { AskRequest } from '@/types/api'
import type { StreamStage } from '@/api/stream'
import { projectsApi, type TopicProject, type StudyMemory } from '@/api/projects'

const controllers = new WeakMap<object, AbortController>()

/**
 * `ready` marks that consent grants and the conversation id were resolved once, so a
 * retry reuses the frozen payload instead of re-asking for a possibly different scope.
 * The entry itself is created before any network call, so a failed or cancelled send
 * still keeps the question on screen and offers 重试.
 */
type Pending = { id: string; ready: boolean; payload: AskRequest & {request_id: string} }

/** Keep diagnostic codes visible without exposing provider messages or unfinished drafts. */
function streamFailureMessage(code: string): string {
  if (code === 'cancelled') return '已停止生成，可以重试确认结果。'
  if (code.includes('consent')) return '此知识库尚未获得所需 AI 处理授权，请联系资料所有者或管理员。'
  if (code === 'conversation_busy') return '上一条问题仍在处理，请稍后重试确认结果。'

  const lengthCodes = ['truncated_or_invalid_completion', 'generation_output_limit', 'invalid_output_budget', 'generation_response_limit']
  const timeoutCodes = ['generation_timeout', 'stream_timeout', 'timeout']
  const validationCodes = ['invalid_citations', 'invalid_citation_format', 'invalid_output_schema', 'generation_invalid_response', 'missing_citations', 'validation_failed']
  const suffix = '未校验的草稿已撤回；已完成的回答不会重复保存。'
  let message = '本次回答未完成，可重试确认结果。'
  if (lengthCodes.includes(code)) message = '回答未能正常结束（可能达到生成长度限制）。建议拆成几个较短的问题，直接重试原问题可能仍会失败。'
  else if (timeoutCodes.includes(code)) message = '生成或流式连接超时，可稍后重试确认结果。'
  else if (validationCodes.includes(code)) message = '回答未通过最终格式或来源校验，可重试确认结果。'
  else if (code === 'network_error' || code === 'invalid_stream') message = '流式连接中断或响应不完整，请检查网络后重试确认结果。'
  // Codes are bounded server-side and are safe to share with QA; never show raw provider errors.
  const diagnostic = /^[a-z_]{1,80}$/.test(code) ? `（诊断码：${code}）` : ''
  return `${message}${suffix}${diagnostic}`
}

export const useChatStore = defineStore('chat', {
  state: () => ({ items: [] as Conversation[], total: 0, active: null as string | null,
    projects: [] as TopicProject[], activeProject: null as string | null,
    messages: [] as ChatMessage[], messageOffset: 0, messageTotal: 0, loading: false, sending: false, error: '', revision: 0,
    pending: null as Pending | null, draft: '', streamStage: null as StreamStage | 'completed' | 'failed' | 'cancelled' | null }),
  actions: {
    cancel() { const pending = this.pending; controllers.get(this)?.abort(); controllers.delete(this); this.sending = false; this.draft = ''; this.streamStage = 'cancelled'; this.error = pending ? '已停止生成。可以重试确认结果；已完成的回答不会重复保存。' : ''; if (pending?.id) void this.reconcileCancelled(pending.id) },
    /**
     * Stopping only closes our reader. The server commits a validated answer if it finished
     * before the disconnect, so pull once and let the transcript match what was actually
     * saved; the "已停止" notice only stays when nothing was persisted.
     */
    async reconcileCancelled(id: string) {
      const rev = this.revision; const epoch = currentEpoch()
      const requestId = this.pending?.payload.request_id
      if (!requestId) return
      const current = () => rev === this.revision && epoch === currentEpoch() && this.active === id
        && this.pending?.id === id && this.pending.payload.request_id === requestId
      const pull = () => conversationsApi.messages(id, this.messageOffset + this.messages.length)
      const committed = (items: ChatMessage[]) => items.some(message =>
        message.role === 'assistant' && message.metadata_json?.request_id === requestId)
      try {
        let page = await pull()
        if (!current()) return
        if (!committed(page.items)) {
          // A commit that raced the disconnect lands shortly after; allow one short retry window.
          await new Promise(done => setTimeout(done, 1200))
          if (!current()) return
          page = await pull()
        }
        const known = new Set(this.messages.map(message => message.id))
        const fresh = page.items.filter(message => !known.has(message.id))
        // Another tab may save an unrelated answer in this conversation; only the
        // matching request may clear this question's retry state.
        if (!committed(fresh)) return
        this.messages.push(...fresh); this.messageTotal = page.total
        this.pending = null; this.error = ''; this.streamStage = 'completed'
      } catch { /* keep the cancel notice; the unverified draft is already withdrawn */ }
    },
    clear() { this.cancel(); this.streamStage = null; this.revision++; this.items = []; this.total = 0; this.active = null; this.activeProject = null; this.projects = []; this.messages = []; this.messageOffset = 0; this.messageTotal = 0; this.loading = false; this.sending = false; this.error = ''; this.pending = null },
    newChat() { this.cancel(); this.streamStage = null; this.revision++; this.active = null; this.messages = []; this.messageOffset = 0; this.messageTotal = 0; this.loading = false; this.pending = null; this.error = '' },
    selectProject(id: string | null) { this.newChat(); this.activeProject = id },
    async listProjects() {
      const epoch = currentEpoch(); const revision = this.revision
      const {items} = await projectsApi.list()
      if (epoch === currentEpoch() && revision === this.revision) this.projects = items
    },
    async createProject(title: string, description = '') {
      const epoch = currentEpoch()
      const project = await projectsApi.create(title, description)
      if (epoch !== currentEpoch()) return
      this.projects.push(project)
      this.selectProject(project.id)
      return project
    },
    async updateProject(id: string, data: {title?: string; description?: string; memory_source_ids?: string[]}) {
      const epoch = currentEpoch()
      const project = await projectsApi.update(id, data)
      if (epoch === currentEpoch()) this.projects = this.projects.map(p => p.id === id ? project : p)
      return project
    },
    async deleteProject(id: string) {
      const epoch = currentEpoch()
      await projectsApi.remove(id)
      if (epoch !== currentEpoch()) return
      this.projects = this.projects.filter(p => p.id !== id).map(p => ({...p, memory_source_ids: p.memory_source_ids.filter(source => source !== id)}))
      this.items = this.items.map(item => item.project_id === id ? {...item, project_id: null} : item)
      if (this.activeProject === id) this.selectProject(null)
    },
    async moveConversation(id: string, projectId: string | null) {
      const epoch = currentEpoch()
      await conversationsApi.move(id, projectId)
      if (epoch !== currentEpoch()) return
      this.items = this.items.map(item => item.id === id ? {...item, project_id: projectId} : item)
      if (this.active === id) this.activeProject = projectId
    },
    async projectMemories(id: string): Promise<StudyMemory[]> {
      const epoch = currentEpoch()
      const notes = (await projectsApi.memories(id)).items
      return epoch === currentEpoch() ? notes : []
    },
    async forgetMemory(id: string, noteId: string) { await projectsApi.forget(id, noteId) },
    async list(more = false) {
      const epoch = currentEpoch(); const revision = this.revision
      const page = await conversationsApi.list(more ? this.items.length : 0)
      if (epoch !== currentEpoch() || revision !== this.revision) return
      this.items = more ? [...this.items, ...page.items] : page.items; this.total = page.total
    },
    async open(id: string) {
      this.cancel(); this.streamStage = null
      const rev = ++this.revision; const epoch = currentEpoch()
      this.activeProject = this.items.find(item => item.id === id)?.project_id ?? null
      this.active = id; this.messages = []; this.messageOffset = 0; this.messageTotal = 0; this.error = ''; this.pending = null; this.loading = true
      try {
        if (!this.items.some(item => item.id === id)) {
          const {conversation} = await conversationsApi.get(id)
          if (rev !== this.revision || epoch !== currentEpoch()) return
          this.activeProject = conversation.project_id ?? null
        }
        // Bounded pages; explicit continuation is offered for longer conversations.
        let page = await conversationsApi.messages(id)
        const offset = Math.max(0, page.total - 100)
        if (offset) page = await conversationsApi.messages(id, offset)
        if (rev === this.revision && epoch === currentEpoch()) { this.messageOffset = offset; this.messages = page.items; this.messageTotal = page.total }
      } catch { if (rev === this.revision && epoch === currentEpoch()) this.error = '无法读取对话，请重新选择或稍后重试。' }
      finally { if (rev === this.revision && epoch === currentEpoch()) this.loading = false }
    },
    async moreMessages() {
      if (!this.active || this.loading) return
      const id = this.active; const rev = this.revision; const epoch = currentEpoch(); this.loading = true
      try { const offset = Math.max(0, this.messageOffset - 100); const page = await conversationsApi.messages(id, offset)
        if (rev === this.revision && epoch === currentEpoch()) { this.messages = [...page.items.filter(m => m.seq < (this.messages[0]?.seq ?? Infinity)), ...this.messages]; this.messageOffset = offset; this.messageTotal = page.total }
      } catch { if (rev === this.revision && epoch === currentEpoch()) this.error = '较早消息加载失败，请重试。' }
      finally { if (rev === this.revision && epoch === currentEpoch()) this.loading = false }
    },
    async rename(id: string, title: string) { const epoch = currentEpoch(); await conversationsApi.rename(id, title); if (epoch === currentEpoch()) await this.list() },
    async remove(id: string) { const epoch = currentEpoch(); await conversationsApi.remove(id); if (epoch !== currentEpoch()) return; if (id === this.active) this.newChat(); await this.list() },
    async send(query: string, ids: string[]) {
      if (this.sending || this.loading || !query.trim() || !ids.length) return
      const epoch = currentEpoch(); const rev = this.revision
      const controller = new AbortController(); controllers.set(this, controller)
      const alive = () => epoch === currentEpoch() && rev === this.revision && controllers.get(this) === controller && !controller.signal.aborted
      this.sending = true; this.error = ''; this.draft = ''; this.streamStage = 'accepted'
      try {
        if (!this.pending) this.pending = { id: this.active ?? '', ready: false, payload: {
          request_id: crypto.randomUUID(), query, knowledge_base_ids: [...ids], answer_mode: 'auto', retrieval_mode: 'hybrid',
          allow_cloud: false, allow_cloud_rerank: false, allow_cloud_generation: false } }
        const pending = this.pending
        if (!pending.ready) {
          const grants = await Promise.all(ids.map(async id => {
            const [records, targets] = await Promise.all([cloudConsentApi.list(id), cloudConsentApi.targets(id)])
            return (purpose: CloudPurpose) => { const target = targets.find(t => t.purpose === purpose); return !!target && records.some(g => g.purpose === purpose && g.service_key === target.service_key && !g.revoked_at) }
          }))
          if (!alive()) return
          pending.payload.allow_cloud = grants.every(g => g('embedding'))
          pending.payload.allow_cloud_rerank = grants.every(g => g('reranking'))
          pending.payload.allow_cloud_generation = grants.every(g => g('generation'))
          if (!this.active) { const created = await conversationsApi.create(query.trim().slice(0, 40), this.activeProject); if (!alive()) return; this.active = created.conversation.id }
          pending.id = this.active ?? ''
          if (!pending.id) return
          pending.ready = true
        }
        await conversationsApi.askStream(pending.id, pending.payload, event => {
          if (!alive()) return
          if (event.type === 'status') this.streamStage = event.payload.stage
          // Keep the draft on `result`: the persisted message only lands after this request
          // settles, so clearing here blanks the answer for the whole follow-up fetch.
          else if (event.type === 'reset' || event.type === 'error') this.draft = ''
          else if (event.type === 'draft') this.draft += event.payload.text
        }, controller.signal)
        if (!alive()) return
        const page = await conversationsApi.messages(pending.id, this.messageOffset + this.messages.length)
        if (!alive()) return
        this.messages.push(...page.items); this.messageTotal = page.total
        this.pending = null; this.sending = false; this.draft = ''; this.streamStage = 'completed'
        try { await this.list() } catch { this.error = '回答已保存，历史列表暂时无法更新，请刷新。' }
      } catch (e) {
        if (!alive()) return
        this.draft = ''; this.streamStage = 'failed'
        const code = e instanceof ApiError ? e.code : ''
        this.error = streamFailureMessage(code)
      } finally { if (controllers.get(this) === controller) { controllers.delete(this); this.draft = ''; if (epoch === currentEpoch() && rev === this.revision) this.sending = false } }
    },
  },
})
