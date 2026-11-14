import { apiUrl } from './config'
import { ensureCsrf, invalidateCsrf } from './csrf'
import { currentEpoch } from './session'
import { ApiError, handleUnauthorized, parseErrorBody } from './http'
import type { AskResponse } from '@/types/api'

export type StreamStage = 'accepted' | 'retrieving' | 'generating' | 'validating' | 'saving'
export type StreamEvent =
  | { type: 'status'; payload: { stage: StreamStage; preview: boolean } }
  | { type: 'reset'; payload: Record<string, never> }
  | { type: 'draft'; payload: { text: string } }
  | { type: 'result'; payload: { result: AskResponse } }
  | { type: 'error'; payload: { code: string; status: number; message: string } }
export type WireEvent = StreamEvent & { seq: number; request_id: string }
const invalid = () => new ApiError(0, 'invalid_stream', '流式响应不完整或格式错误')
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const fields = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).sort().join() === keys.sort().join()

export function parseEvent(raw: string, kind: string, seq: number, requestId: string): WireEvent {
  const event: unknown = JSON.parse(raw)
  if (!object(event) || !fields(event, ['type','seq','request_id','payload']) || event.type !== kind || event.seq !== seq || event.request_id !== requestId || !object(event.payload)) throw invalid()
  const p = event.payload
  if (kind === 'status') {
    if (!fields(p,['stage','preview']) || !['accepted','retrieving','generating','validating','saving'].includes(String(p.stage)) || typeof p.preview !== 'boolean') throw invalid()
  } else if (kind === 'reset') { if (!fields(p,[])) throw invalid() }
  else if (kind === 'draft') { if (!fields(p,['text']) || typeof p.text !== 'string' || !p.text.length || p.text.length > 32000) throw invalid() }
  else if (kind === 'error') {
    if (!fields(p,['code','status','message']) || typeof p.code !== 'string' || !/^[a-z_]{1,80}$/.test(p.code) || typeof p.status !== 'number' || !Number.isInteger(p.status) || p.status < 400 || p.status > 599 || typeof p.message !== 'string') throw invalid()
  } else if (kind === 'result') {
    if (!fields(p,['result']) || !object(p.result)) throw invalid()
    const r=p.result
    if (!['answered','insufficient_evidence','out_of_scope'].includes(String(r.status)) || (typeof r.answer !== 'string' && r.answer !== null) || (typeof r.answer === 'string' && r.answer.length > 32000) || !Array.isArray(r.sources) || r.sources.length > 20
      || !r.sources.every(s => object(s) && typeof s.citation_id === 'string' && /^\[S[1-9][0-9]?\]$/.test(s.citation_id)) || typeof r.latency_ms !== 'number' || !Number.isFinite(r.latency_ms)) throw invalid()
  } else throw invalid()
  return event as WireEvent
}

/** Bounded CR/LF-aware SSE framer; UTF-8 decoding happens once at the network boundary. */
export class EventFrames {
  private line=''; private data: string[]=[]; private kind=''; private id=''; private size=0; private cr=false
  feed(text: string): { data: string; kind: string; id: string }[] {
    const result: {data:string;kind:string;id:string}[]=[]
    for (const ch of text) {
      if (this.cr) { this.cr=false; if (ch === '\n') continue }
      if (ch === '\r' || ch === '\n') {
        if (ch === '\r') this.cr=true
        const line=this.line;this.line=''
        if (!line) {
          if (this.data.length) result.push({data:this.data.join('\n'),kind:this.kind,id:this.id})
          this.data=[];this.kind='';this.id='';this.size=0
        } else if (!line.startsWith(':')) {
          const split=line.indexOf(':'),name=split < 0 ? line : line.slice(0,split),value=split < 0 ? '' : line.slice(split+1).replace(/^ /,'')
          if (name === 'data') this.data.push(value)
          else if (name === 'event') this.kind=value
          else if (name === 'id') this.id=value
        }
      } else { this.line+=ch;this.size++;if(this.size>262144)throw invalid() }
    }
    return result
  }
}

function abortable<T>(job: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(new DOMException('Aborted','AbortError'))
  return new Promise((resolve,reject)=>{
    const abort=()=>reject(new DOMException('Aborted','AbortError'))
    signal.addEventListener('abort',abort,{once:true})
    job.then(resolve,reject).finally(()=>signal.removeEventListener('abort',abort))
  })
}

export async function requestStream(path: string, payload: { request_id: string }, onEvent: (e: WireEvent)=>void, signal: AbortSignal): Promise<AskResponse> {
  const epoch=currentEpoch(),controller=new AbortController()
  const abort=()=>controller.abort();signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort()
  let timedOut=false,idle: ReturnType<typeof setTimeout> | undefined
  const timeout=()=>{timedOut=true;controller.abort()}
  const total=setTimeout(timeout,125000)
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  try {
    let response: Response | undefined
    for(let attempt=0;attempt<2;attempt++) {
      const token=await abortable(ensureCsrf(),controller.signal)
      if (controller.signal.aborted || epoch!==currentEpoch()) throw new DOMException('Aborted','AbortError')
      response=await fetch(apiUrl(path),{method:'POST',credentials:'include',cache:'no-store',signal:controller.signal,
        headers:{Accept:'text/event-stream','Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(payload)})
      if(response.status===403 && attempt===0) {
        const error=await parseErrorBody(response.clone())
        if(error.code==='csrf_rejected') { invalidateCsrf();await response.body?.cancel();continue }
      }
      break
    }
    if (!response) throw invalid()
    if (response.status===401) handleUnauthorized(epoch)
    if(!response.ok) { const error=await parseErrorBody(response);throw new ApiError(response.status,error.code,error.message) }
    if(response.headers.get('Content-Type')?.split(';')[0]?.trim()!=='text/event-stream' || !response.body) throw invalid()
    reader=response.body.getReader()
    const decoder=new TextDecoder('utf-8',{fatal:true}),frames=new EventFrames()
    let seq=0,bytes=0,draftBytes=0,generating=false
    while(true) {
      clearTimeout(idle);idle=setTimeout(timeout,30000)
      const {value,done}=await abortable(reader.read(),controller.signal)
      if(epoch!==currentEpoch() || signal.aborted)throw new DOMException('Aborted','AbortError')
      if(done)throw invalid() // a successful stream must have an explicit terminal event
      bytes+=value.byteLength;if(bytes>2*1024*1024)throw invalid()
      for(const frame of frames.feed(decoder.decode(value,{stream:true}))) {
        if(++seq>8192 || frame.id!==String(seq))throw invalid()
        const event=parseEvent(frame.data,frame.kind,seq,payload.request_id)
        if(event.type==='draft') {
          draftBytes+=new TextEncoder().encode(event.payload.text).length
          if(!generating || draftBytes>32000)throw invalid()
        } else if(event.type==='reset') { draftBytes=0;generating=false }
        else if(event.type==='status') generating=event.payload.stage==='generating' && event.payload.preview
        if(event.type==='error') {
          if(event.payload.status===401)handleUnauthorized(epoch)
          onEvent(event);throw new ApiError(event.payload.status,event.payload.code,'回答未完成')
        }
        onEvent(event)
        if(event.type==='result')return event.payload.result
      }
    }
  } catch(error) {
    if(error instanceof ApiError)throw error
    if(controller.signal.aborted)throw new ApiError(0,timedOut?'timeout':'cancelled',timedOut?'请求超时':'已停止生成')
    if(error instanceof SyntaxError || error instanceof TypeError && /encoding|encoded|decode/i.test(error.message))throw invalid()
    throw new ApiError(0,'network_error','流式连接中断')
  } finally {
    controller.abort();clearTimeout(total);clearTimeout(idle);signal.removeEventListener('abort',abort)
    try { await reader?.cancel() } catch { /* closed network stream */ }
    reader?.releaseLock()
  }
}
