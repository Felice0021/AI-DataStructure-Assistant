import { defineStore } from 'pinia'
import { conversationsApi, type Conversation, type ChatMessage } from '@/api/conversations'
import { cloudConsentApi, type CloudPurpose } from '@/api/cloudConsent'
import { currentEpoch } from '@/api/session'
import { ApiError } from '@/api/http'
import type { AskRequest } from '@/types/api'
import type { StreamStage } from '@/api/stream'

const controllers = new WeakMap<object, AbortController>()

type Pending = { id: string; payload: AskRequest & {request_id: string} }
export const useChatStore = defineStore('chat', {
  state: () => ({ items: [] as Conversation[], total: 0, active: null as string | null,
    messages: [] as ChatMessage[], messageOffset: 0, messageTotal: 0, loading: false, sending: false, error: '', revision: 0,
    pending: null as Pending | null, draft: '', streamStage: null as StreamStage | 'completed' | 'failed' | 'cancelled' | null }),
  actions: {
    cancel() { controllers.get(this)?.abort(); controllers.delete(this); this.sending = false; this.draft = ''; this.streamStage = 'cancelled'; this.error = this.pending ? '已停止生成。可以重试确认结果；已完成的回答不会重复保存。' : '' },
    clear() { this.cancel(); this.streamStage = null; this.revision++; this.items = []; this.total = 0; this.active = null; this.messages = []; this.messageOffset = 0; this.messageTotal = 0; this.loading = false; this.sending = false; this.error = ''; this.pending = null },
    newChat() { this.cancel(); this.streamStage = null; this.revision++; this.active = null; this.messages = []; this.messageOffset = 0; this.messageTotal = 0; this.loading = false; this.pending = null; this.error = '' },
    async list(more = false) {
      const epoch = currentEpoch(); const revision = this.revision
      const page = await conversationsApi.list(more ? this.items.length : 0)
      if (epoch !== currentEpoch() || revision !== this.revision) return
      this.items = more ? [...this.items, ...page.items] : page.items; this.total = page.total
    },
    async open(id: string) {
      this.cancel(); this.streamStage = null
      const rev = ++this.revision; const epoch = currentEpoch()
      this.active = id; this.messages = []; this.messageOffset = 0; this.messageTotal = 0; this.error = ''; this.pending = null; this.loading = true
      try {
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
        if (!this.pending) {
          const grants = await Promise.all(ids.map(async id => {
            const [records, targets] = await Promise.all([cloudConsentApi.list(id), cloudConsentApi.targets(id)])
            return (purpose: CloudPurpose) => { const target = targets.find(t => t.purpose === purpose); return !!target && records.some(g => g.purpose === purpose && g.service_key === target.service_key && !g.revoked_at) }
          }))
          if (!alive()) return
          if (!this.active) { const created = await conversationsApi.create(query.trim().slice(0, 40)); if (!alive()) return; this.active = created.conversation.id }
          this.pending = {id: this.active, payload: {request_id: crypto.randomUUID(), query, knowledge_base_ids: [...ids], answer_mode: 'auto', retrieval_mode: 'hybrid',
            allow_cloud: grants.every(g => g('embedding')), allow_cloud_rerank: grants.every(g => g('reranking')), allow_cloud_generation: grants.every(g => g('generation'))}}
        }
        const pending = this.pending
        await conversationsApi.askStream(pending.id, pending.payload, event => {
          if (!alive()) return
          if (event.type === 'status') this.streamStage = event.payload.stage
          else if (event.type === 'reset' || event.type === 'result' || event.type === 'error') this.draft = ''
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
        this.error = code === 'cancelled' ? '已停止生成，可以重试确认结果。' : code.includes('consent') ? '此知识库尚未获得所需 AI 处理授权，请联系资料所有者或管理员。' : code === 'conversation_busy' ? '上一条问题仍在处理，请稍后重试确认结果。' : '本次回答未完成。可重试确认结果；重试不会重复保存已完成的回答。'
      } finally { if (controllers.get(this) === controller) { controllers.delete(this); this.draft = ''; if (epoch === currentEpoch() && rev === this.revision) this.sending = false } }
    },
  },
})
