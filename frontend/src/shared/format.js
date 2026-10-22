// ============================================================
// 通用格式化工具
// ============================================================

/** 生成会话 ID（优先使用浏览器原生 UUID） */
export function createSessionId() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID().replace(/-/g, '')
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
}

/** 当前时间 HH:mm */
export function nowTime() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 文件大小格式化 */
export function formatBytes(size) {
  const num = Number(size) || 0
  if (num < 1024) return `${num} B`
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`
  return `${(num / 1024 / 1024).toFixed(1)} MB`
}

/** 文件处理状态中文名 */
export const STATUS_LABELS = {
  pending: '等待处理',
  parsing: '解析中',
  chunking: '切片中',
  tagging: '打标签',
  embedding: '向量化',
  kg: '图谱抽取',
  done: '已完成',
  failed: '处理失败'
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || '未知'
}

/** 状态对应的样式类 */
export function statusClass(status) {
  if (status === 'done') return 'done'
  if (status === 'failed') return 'failed'
  if (status === 'pending') return ''
  return 'running'
}

/** 处理中的状态集合：用于判断是否需要继续轮询 */
export const RUNNING_STATUS = ['pending', 'parsing', 'chunking', 'tagging', 'embedding', 'kg']
