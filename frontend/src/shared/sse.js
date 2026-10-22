// ============================================================
// SSE 流式问答客户端
// 使用 fetch + ReadableStream 读取 text/event-stream，
// 这样管理端可以携带 Authorization 头（原生 EventSource 不支持自定义头）。
// 事件：meta / status / sources / delta / done / error
// ============================================================
import { API_BASE } from './api'

/**
 * 发起流式问答。
 * @param {object} params
 * @param {string} params.question 问题
 * @param {string} params.sessionId 会话 ID
 * @param {string} params.token 管理员 Token（客户端为空）
 * @param {AbortSignal} params.signal 中断信号
 * @param {Function} params.onMeta 会话信息
 * @param {Function} params.onStatus 检索阶段提示
 * @param {Function} params.onSources 回答出处（知识库片段 + 图谱三元组）
 * @param {Function} params.onDelta 增量文本
 * @param {Function} params.onDone 结束
 * @param {Function} params.onError 错误
 */
export async function streamChat({
  question,
  sessionId,
  token = '',
  signal,
  onMeta,
  onStatus,
  onSources,
  onDelta,
  onDone,
  onError
}) {
  const query = token ? `?token=${encodeURIComponent(token)}` : ''
  let resp
  try {
    resp = await fetch(`${API_BASE}/chat/stream${query}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream'
      },
      body: JSON.stringify({ question, session_id: sessionId }),
      signal
    })
  } catch (err) {
    if (err.name === 'AbortError') return
    throw new Error('无法连接问答服务，请确认后端已启动')
  }

  const contentType = resp.headers.get('content-type') || ''

  // 非 SSE 响应（通常是参数错误 / 服务异常），解析统一 JSON 后抛出
  if (!contentType.includes('text/event-stream')) {
    let message = `问答服务异常（HTTP ${resp.status}）`
    try {
      const json = await resp.json()
      message = json.msg || message
    } catch (err) {
      // 忽略解析失败，使用默认提示
    }
    throw new Error(message)
  }

  if (!resp.body) {
    throw new Error('当前浏览器不支持流式响应，请更换浏览器')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finished = false

  const handleFrame = (raw) => {
    if (!raw.trim()) return
    let event = 'message'
    const dataLines = []
    for (const line of raw.split(/\r?\n/)) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).replace(/^ /, ''))
      }
    }
    if (!dataLines.length) return

    let data = {}
    try {
      data = JSON.parse(dataLines.join('\n'))
    } catch (err) {
      return
    }

    if (event === 'meta' && onMeta) onMeta(data)
    else if (event === 'status' && onStatus) onStatus(data)
    else if (event === 'sources' && onSources) onSources(data)
    else if (event === 'delta' && onDelta) onDelta(data.content || '')
    else if (event === 'done') {
      finished = true
      if (onDone) onDone(data)
    } else if (event === 'error') {
      finished = true
      if (onError) onError(data.message || '回答生成失败')
    }
  }

  try {
    while (!finished) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let index = buffer.indexOf('\n\n')
      while (index !== -1) {
        const frame = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)
        handleFrame(frame)
        if (finished) break
        index = buffer.indexOf('\n\n')
      }
    }
    // 处理最后一个没有以空行结尾的帧
    if (!finished && buffer.trim()) handleFrame(buffer)
  } catch (err) {
    if (err.name === 'AbortError') return
    throw new Error('流式连接中断，请重试')
  } finally {
    try {
      reader.releaseLock()
    } catch (err) {
      // 已释放时忽略
    }
  }
}
