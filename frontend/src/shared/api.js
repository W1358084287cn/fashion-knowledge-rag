// ============================================================
// 统一请求封装
// - 自动拼接 /api 前缀（开发环境由 Vite 代理，生产由 FastAPI 同源托管）
// - 自动携带管理员 Token
// - 统一解析 { code, msg, data }
// - 401 / code=1002 时广播事件，让管理端自动退出登录
// ============================================================
export const API_BASE = import.meta.env.VITE_API_BASE || '/api'
export const TOKEN_KEY = 'fashion_admin_token'
export const ADMIN_NAME_KEY = 'fashion_admin_name'
// 客户端普通用户登录态（与管理端完全隔离，互不影响）
export const USER_TOKEN_KEY = 'fashion_user_token'
export const USER_NAME_KEY = 'fashion_user_name'
export const USER_ID_KEY = 'fashion_user_id'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token, username = '') {
  localStorage.setItem(TOKEN_KEY, token)
  if (username) localStorage.setItem(ADMIN_NAME_KEY, username)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ADMIN_NAME_KEY)
}

export function getAdminName() {
  return localStorage.getItem(ADMIN_NAME_KEY) || 'admin'
}

/** ---------- 客户端普通用户登录态 ---------- */
export function getUserToken() {
  return localStorage.getItem(USER_TOKEN_KEY) || ''
}

export function getUserName() {
  return localStorage.getItem(USER_NAME_KEY) || ''
}

export function getUserId() {
  return localStorage.getItem(USER_ID_KEY) || ''
}

export function setUserSession(data) {
  localStorage.setItem(USER_TOKEN_KEY, data.token || '')
  localStorage.setItem(USER_NAME_KEY, data.display_name || data.username || '')
  localStorage.setItem(USER_ID_KEY, String(data.user_id || ''))
}

export function clearUserSession() {
  localStorage.removeItem(USER_TOKEN_KEY)
  localStorage.removeItem(USER_NAME_KEY)
  localStorage.removeItem(USER_ID_KEY)
}

/**
 * 发起请求并返回 data 字段。
 * @param {string} path 以 / 开头，如 /admin/login
 * @param {object} options { method, body, token, signal, timeout }
 */
export async function request(path, options = {}) {
  const {
    method = 'GET',
    body = null,
    token = '',
    signal = null,
    timeout = 20000
  } = options

  const headers = { ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`

  let payload
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  // 超时控制：避免后端未启动时页面一直转圈
  const controller = signal ? null : new AbortController()
  const timer = controller ? setTimeout(() => controller.abort(), timeout) : null

  let resp
  try {
    resp = await fetch(API_BASE + path, {
      method,
      headers,
      body: payload,
      signal: signal || (controller ? controller.signal : undefined)
    })
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('请求超时，请确认后端服务已启动')
    }
    throw new Error('网络异常，无法连接服务器')
  } finally {
    if (timer) clearTimeout(timer)
  }

  let json
  try {
    json = await resp.json()
  } catch (err) {
    throw new Error(`服务返回异常（HTTP ${resp.status}）`)
  }

  if (json.code !== 0) {
    const error = new Error(json.msg || '请求失败')
    error.code = json.code
    error.status = resp.status
    error.data = json.data
    // 管理端登录失效：通知外壳组件清理本地缓存
    if (json.code === 1002 && token) {
      window.dispatchEvent(new Event('admin-unauthorized'))
    }
    throw error
  }
  return json.data
}
