import { beforeEach,afterEach,expect,it,vi } from 'vitest'
import { EventFrames,parseEvent,requestStream,type WireEvent } from './stream'
import { invalidateCsrf } from './csrf'
import { ApiError,setUnauthorizedHandler } from './http'
import { bumpEpoch } from './session'
import { mockAnswered } from '@/mocks/fixtures'

const requestId='11111111-1111-4111-8111-111111111111'
const packet=(seq:number,type:string,payload:unknown,id=requestId)=>`event: ${type}\r\nid: ${seq}\r\ndata: ${JSON.stringify({type,seq,request_id:id,payload})}\r\n\r\n`
const status=(seq:number)=>packet(seq,'status',{stage:'generating',preview:true})
const result=(seq:number)=>packet(seq,'result',{result:mockAnswered})
const encoder=new TextEncoder()
let fetcher:ReturnType<typeof vi.fn>
beforeEach(()=>{
  invalidateCsrf();fetcher=vi.fn();vi.stubGlobal('fetch',fetcher)
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({csrf_token:'synthetic-csrf-for-mock-only'}),{headers:{'Content-Type':'application/json'}}))
})
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();setUnauthorizedHandler(null)})
function body(text:string,step=3) {
  const bytes=encoder.encode(text)
  return new ReadableStream<Uint8Array>({start(controller){for(let i=0;i<bytes.length;i+=step)controller.enqueue(bytes.slice(i,i+step));controller.close()}})
}
const response=(text:string)=>new Response(body(text),{headers:{'Content-Type':'text/event-stream'}})

it('consumes split UTF-8 and CRLF frames immediately, preserving cookie/CSRF and request identity',async()=>{
  const events:WireEvent[]=[]
  fetcher.mockResolvedValueOnce(response(': heartbeat\r\n\r\n'+status(1)+packet(2,'draft',{text:'中文😀 [S1]'})+result(3)))
  const output=await requestStream('/conversations/one/ask-stream',{request_id:requestId},e=>events.push(e),new AbortController().signal)
  expect(events.map(e=>e.type)).toEqual(['status','draft','result']);expect(output).toEqual(mockAnswered)
  const options=fetcher.mock.calls[1]![1]
  expect(options.credentials).toBe('include');expect(options.headers['X-CSRF-Token']).toBeTruthy()
  expect(options.headers.Accept).toBe('text/event-stream');expect(options.headers.Origin).toBeUndefined()
  expect(options.cache).toBe('no-store')
})

it('delivers a genuine draft before the terminal response is available',async()=>{
  let channel!:ReadableStreamDefaultController<Uint8Array>
  fetcher.mockResolvedValueOnce(new Response(new ReadableStream({start(c){channel=c}}),{headers:{'Content-Type':'text/event-stream'}}))
  const events:WireEvent[]=[];let complete=false
  const job=requestStream('/stream',{request_id:requestId},e=>events.push(e),new AbortController().signal).then(r=>{complete=true;return r})
  await vi.waitFor(()=>expect(channel).toBeDefined())
  channel.enqueue(encoder.encode(status(1)+packet(2,'draft',{text:'正文先到达'})))
  await vi.waitFor(()=>expect(events).toHaveLength(2));expect(complete).toBe(false)
  channel.enqueue(encoder.encode(result(3)));channel.close();await job
  expect(complete).toBe(true)
})

it('does not silently retry a broken/invalid stream after receiving data',async()=>{
  fetcher.mockResolvedValueOnce(response(status(1)+packet(2,'draft',{text:'未核实文本'})))
  await expect(requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)).rejects.toMatchObject({code:'invalid_stream'})
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('refreshes CSRF once before streaming, never retries ordinary forbidden',async()=>{
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({error:{code:'csrf_rejected',message:'rejected'}}),{status:403}))
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({csrf_token:'synthetic-refreshed'})))
  fetcher.mockResolvedValueOnce(response(result(1)))
  await requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)
  expect(fetcher).toHaveBeenCalledTimes(4)
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({error:{code:'forbidden',message:'rejected'}}),{status:403}))
  await expect(requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)).rejects.toMatchObject({code:'forbidden'})
  expect(fetcher).toHaveBeenCalledTimes(5)
})

it('handles session revocation in a terminal SSE error and ignores an old account’s 401',async()=>{
  const handler=vi.fn();setUnauthorizedHandler(handler)
  fetcher.mockResolvedValueOnce(response(packet(1,'error',{code:'unauthorized',status:401,message:'Answer unavailable'})))
  await expect(requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)).rejects.toMatchObject({status:401})
  expect(handler).toHaveBeenCalledTimes(1)
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({csrf_token:'synthetic-after-revoke'})))
  let resolve!: (r:Response)=>void
  fetcher.mockImplementationOnce(()=>new Promise(r=>{resolve=r}))
  const job=requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)
  await vi.waitFor(()=>expect(resolve).toBeDefined());bumpEpoch()
  resolve(new Response(JSON.stringify({error:{code:'unauthorized'}}),{status:401}))
  await expect(job).rejects.toBeInstanceOf(ApiError);expect(handler).toHaveBeenCalledTimes(1)
})

it('user cancellation and read idle timeout close the reader without retrying',async()=>{
  const cancelled=vi.fn()
  fetcher.mockResolvedValueOnce(new Response(new ReadableStream({cancel:cancelled}),{headers:{'Content-Type':'text/event-stream'}}))
  const control=new AbortController(),job=requestStream('/stream',{request_id:requestId},()=>{},control.signal)
  await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(2));control.abort()
  await expect(job).rejects.toMatchObject({code:'cancelled'});expect(cancelled).toHaveBeenCalled()
  vi.useFakeTimers()
  fetcher.mockResolvedValueOnce(new Response(new ReadableStream(),{headers:{'Content-Type':'text/event-stream'}}))
  const timeout=requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)
  const checked=expect(timeout).rejects.toMatchObject({code:'timeout'})
  await vi.advanceTimersByTimeAsync(30001);await checked
})

it('rejects out-of-order, wrong-request, nonterminal result and pre-generation drafts',async()=>{
  for(const text of [result(2),packet(1,'draft',{text:'premature'}),packet(1,'result',{result:mockAnswered},'other'),packet(1,'result',{result:{...mockAnswered,status:'validation_failed'}})]) {
    fetcher.mockResolvedValueOnce(response(text))
    await expect(requestStream('/stream',{request_id:requestId},()=>{},new AbortController().signal)).rejects.toMatchObject({code:'invalid_stream'})
  }
  expect(()=>parseEvent('{"type":"x"}','x',1,requestId)).toThrow()
  expect(()=>new EventFrames().feed('a'.repeat(262145))).toThrow()
})
