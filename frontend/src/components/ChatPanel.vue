<template>
  <section class="chat-panel">
    <!-- 会话侧栏：新开对话 + 本人历史对话（客户端只看自己的，管理端只看测试对话） -->
    <div v-if="drawerOpen" class="session-drawer">
      <div class="drawer-head">
        <span class="drawer-title">我的对话</span>
        <button class="btn btn-ghost btn-sm" type="button" @click="drawerOpen = false">关闭</button>
      </div>
      <button class="btn btn-primary btn-sm new-chat" type="button" @click="startNewChat">
        新开对话
      </button>
      <div v-if="loadingSessions" class="empty-list">加载中…</div>
      <div v-else-if="!sessions.length" class="empty-list">还没有历史对话</div>
      <ul v-else class="session-list">
        <li
          v-for="item in sessions"
          :key="item.session_id"
          class="session-item"
          :class="{ active: item.session_id === sessionId }"
        >
          <button class="session-main" type="button" @click="switchSession(item.session_id)">
            <span class="session-title">{{ item.title }}</span>
            <span class="session-meta">{{ item.last_at }} · {{ item.message_count }} 条</span>
          </button>
          <button class="session-del" type="button" title="删除该对话" @click.stop="removeSession(item)">×</button>
        </li>
      </ul>
    </div>
    <div v-if="drawerOpen" class="drawer-mask" @click="drawerOpen = false"></div>

    <!-- 消息区 -->
    <div ref="bodyRef" class="chat-body">
      <div v-if="messages.length === 0 && !loadingHistory" class="empty-state">
        <div class="empty-mark">衣</div>
        <h2 class="empty-title">服装智能客服</h2>
        <p class="empty-desc">面料、尺码、售后、保养问题，都可以问我</p>
        <div class="chips">
          <button
            v-for="item in suggestions"
            :key="item"
            class="chip"
            type="button"
            @click="send(item)"
          >
            {{ item }}
          </button>
        </div>
      </div>

      <div v-else class="chat-list">
        <div
          v-for="(msg, index) in messages"
          :key="index"
          class="msg"
          :class="msg.role"
        >
          <div v-if="msg.role === 'assistant'" class="msg-avatar">衣</div>
          <div class="bubble-wrap">
            <div class="bubble">
              <span v-if="msg.streaming && !msg.content" class="typing">
                <i></i><i></i><i></i>
              </span>
              <span v-else>{{ msg.content }}</span>
            </div>
            <!-- 回答出处：命中的知识库片段 + 知识图谱三元组，可展开核对 -->
            <details v-if="msg.sources && sourceCount(msg.sources)" class="sources">
              <summary>参考来源（{{ sourceCount(msg.sources) }}）</summary>
              <div class="sources-body">
                <div
                  v-for="doc in msg.sources.documents"
                  :key="'d' + doc.index"
                  class="source-doc"
                >
                  <div class="source-line">
                    <span class="source-index">资料 {{ doc.index }}</span>
                    <span class="source-file">{{ doc.file_name }}</span>
                    <span v-if="doc.goods_no" class="source-meta">{{ doc.goods_no }}</span>
                    <span v-if="doc.category" class="source-meta">{{ doc.category }}</span>
                  </div>
                  <div class="source-snippet">{{ doc.snippet }}</div>
                </div>
                <div v-if="msg.sources.triples && msg.sources.triples.length" class="source-kg">
                  <div class="source-line">
                    <span class="source-index">图谱</span>
                    <span class="source-file">知识图谱关联事实</span>
                  </div>
                  <div
                    v-for="(t, ti) in msg.sources.triples"
                    :key="'t' + ti"
                    class="kg-line"
                  >
                    {{ t.head }} <span class="kg-rel">{{ t.relation }}</span> {{ t.tail }}
                  </div>
                </div>
              </div>
            </details>
            <div v-if="msg.streaming && msg.status" class="msg-status">
              <span class="dot-pulse"></span>{{ msg.status }}
            </div>
            <div v-if="!msg.streaming && msg.time" class="msg-time">{{ msg.time }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="errorMsg" class="banner">{{ errorMsg }}</div>

    <!-- 输入区 -->
    <div class="composer">
      <div class="composer-bar">
        <button class="composer-icon" type="button" title="历史对话" @click="openDrawer">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 6H20M4 12H20M4 18H14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
          </svg>
        </button>
        <button class="composer-icon" type="button" title="新开对话" @click="startNewChat">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
          </svg>
        </button>
      </div>
      <div class="composer-inner">
        <textarea
          ref="inputRef"
          v-model="input"
          rows="1"
          maxlength="500"
          placeholder="输入你的问题…"
          @input="autoResize"
          @keydown="onKeydown"
        ></textarea>
        <button
          v-if="streaming"
          class="send-btn stop"
          type="button"
          aria-label="停止生成"
          @click="stop"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <rect x="2.5" y="2.5" width="9" height="9" rx="1.5" fill="currentColor" />
          </svg>
        </button>
        <button
          v-else
          class="send-btn"
          type="button"
          :disabled="!input.trim()"
          aria-label="发送"
          @click="send()"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 12L20 4L14 20L11 13L4 12Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
      <p class="composer-hint">回答仅基于已上传的服装知识库与知识图谱</p>
    </div>
  </section>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { request } from '../shared/api'
import { streamChat } from '../shared/sse'
import { createSessionId, nowTime } from '../shared/format'

const props = defineProps({
  /** client：客户端；admin：管理端测试页 */
  mode: { type: String, default: 'client' },
  /** 登录 Token：客户端为用户 Token，管理端为管理员 Token */
  token: { type: String, default: '' },
  /** 登录身份变化时用于重置会话（如重新登录） */
  identity: { type: String, default: '' },
  /** 会话缓存作用域：客户端传用户 ID，管理端固定 admin，避免不同账号串历史 */
  scope: { type: String, default: '' }
})

const suggestions = [
  '这款大衣是什么面料？',
  '身高 165cm 体重 55kg 选什么尺码？',
  '支持七天无理由退换吗？',
  '羊毛大衣怎么保养？'
]

const messages = ref([])
const input = ref('')
const streaming = ref(false)
const statusText = ref('')
const errorMsg = ref('')
const loadingHistory = ref(false)
const bodyRef = ref(null)
const inputRef = ref(null)
let controller = null

// 管理端与客户端、不同客户端账号使用不同的会话缓存 key，历史互不干扰
const sessionKey = `fashion_session_${props.mode}_${props.scope || 'default'}`
const sessionId = ref('')

// 会话抽屉：列出当前身份本人的历史对话，可切换 / 删除
const drawerOpen = ref(false)
const sessions = ref([])
const loadingSessions = ref(false)

function ensureSession() {
  let sid = localStorage.getItem(sessionKey)
  if (!sid) {
    sid = createSessionId()
    localStorage.setItem(sessionKey, sid)
  }
  sessionId.value = sid
}

/** 参考来源条目总数（文档片段 + 图谱三元组），为 0 时不展示来源区域 */
function sourceCount(sources) {
  if (!sources) return 0
  const docs = Array.isArray(sources.documents) ? sources.documents.length : 0
  const triples = Array.isArray(sources.triples) ? sources.triples.length : 0
  return docs + triples
}

function scrollBottom() {
  nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function autoResize(event) {
  const el = event.target
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 108)}px`
}

function onKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  send()
}

/** 发送问题并接收流式回答 */
async function send(text) {
  const question = String(text ?? input.value ?? '').trim()
  if (!question || streaming.value) return

  input.value = ''
  errorMsg.value = ''
  statusText.value = ''
  if (inputRef.value) inputRef.value.style.height = 'auto'

  messages.value.push({ role: 'user', content: question, time: nowTime() })

  const assistant = reactive({
    role: 'assistant',
    content: '',
    time: '',
    streaming: true,
    status: '正在理解你的问题',
    sources: null
  })
  messages.value.push(assistant)
  streaming.value = true
  scrollBottom()

  controller = new AbortController()

  try {
    await streamChat({
      question,
      sessionId: sessionId.value,
      token: ***,
      signal: controller.signal,
      onMeta: (data) => {
        if (data.session_id) {
          sessionId.value = data.session_id
          localStorage.setItem(sessionKey, data.session_id)
        }
      },
      onStatus: (data) => {
        assistant.status = data.message || ''
        scrollBottom()
      },
      onSources: (data) => {
        assistant.sources = data
      },
      onDelta: (content) => {
        assistant.content += content
        assistant.status = ''
        scrollBottom()
      },
      onDone: () => {
        assistant.status = ''
        assistant.time = nowTime()
        assistant.streaming = false
        scrollBottom()
      },
      onError: (message) => {
        errorMsg.value = message
        if (!assistant.content) assistant.content = '回答失败，请稍后重试。'
        assistant.status = ''
      }
    })
  } catch (err) {
    errorMsg.value = err.message || '网络异常，请稍后重试'
    if (!assistant.content) assistant.content = '回答失败，请稍后重试。'
  } finally {
    assistant.streaming = false
    assistant.status = ''
    if (!assistant.time) assistant.time = nowTime()
    streaming.value = false
    statusText.value = ''
    controller = null
    scrollBottom()
  }
}

function stop() {
  if (controller) controller.abort()
  streaming.value = false
}

/** 新开对话：生成新会话 ID，旧历史保留在服务端，可在历史列表里找回 */
function startNewChat() {
  if (streaming.value) stop()
  messages.value = []
  errorMsg.value = ''
  const sid = createSessionId()
  sessionId.value = sid
  localStorage.setItem(sessionKey, sid)
  drawerOpen.value = false
  loadHistory()
}

/** 打开历史对话列表 */
async function openDrawer() {
  drawerOpen.value = true
  await loadSessions()
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const query = props.token ? `?token=${encodeURIComponent(props.token)}&limit=50` : '?limit=50'
    const data = await request(`/chat/sessions${query}`)
    sessions.value = data.items || []
  } catch (err) {
    sessions.value = []
  } finally {
    loadingSessions.value = false
  }
}

/** 切换到某个历史会话 */
async function switchSession(sid) {
  if (streaming.value) return
  sessionId.value = sid
  localStorage.setItem(sessionKey, sid)
  drawerOpen.value = false
  await loadHistory()
}

/** 删除某个历史会话 */
async function removeSession(item) {
  if (!window.confirm(`确定删除对话「${item.title}」吗？`)) return
  try {
    const query = props.token ? `?token=${encodeURIComponent(props.token)}` : ''
    await request(`/chat/sessions/${encodeURIComponent(item.session_id)}${query}`, { method: 'DELETE' })
    sessions.value = sessions.value.filter((s) => s.session_id !== item.session_id)
    if (item.session_id === sessionId.value) startNewChat()
  } catch (err) {
    errorMsg.value = err.message || '删除失败'
  }
}

/** 加载历史对话（刷新页面后恢复当前会话） */
async function loadHistory() {
  if (!sessionId.value) return
  loadingHistory.value = true
  try {
    // 带上 Token：服务端据此只返回当前身份自己的消息，避免跨账号读取
    const auth = props.token ? `&token=${encodeURIComponent(props.token)}` : ''
    const data = await request(`/chat/history?session_id=${encodeURIComponent(sessionId.value)}&limit=100${auth}`)
    const items = data.items || []
    messages.value = items.map((item) => ({
      role: item.role,
      content: item.content,
      time: item.created_at ? item.created_at.slice(11, 16) : '',
      streaming: false
    }))
    scrollBottom()
  } catch (err) {
    if (messages.value.length === 0) errorMsg.value = ''
  } finally {
    loadingHistory.value = false
  }
}

onMounted(() => {
  ensureSession()
  loadHistory()
})

// 父组件头部按钮：新对话 / 历史
defineExpose({ startNewChat, openDrawer, send, loadSessions })
</script>

<style scoped>
.chat-panel {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.session-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  width: min(84%, 320px);
  padding: 12px;
  background: var(--surface);
  border-left: 1px solid var(--line);
  box-shadow: -8px 0 24px rgba(38, 37, 35, 0.08);
}

.drawer-mask {
  position: absolute;
  inset: 0;
  z-index: 15;
  background: rgba(38, 37, 35, 0.18);
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.drawer-title {
  font-size: 14px;
  font-weight: 600;
}

.new-chat {
  width: 100%;
  margin-bottom: 10px;
}

.session-list {
  flex: 1;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-y: auto;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-bottom: 1px dashed var(--line);
}

.session-item.active {
  background: var(--accent-soft);
  border-radius: 8px;
}

.session-main {
  flex: 1;
  min-width: 0;
  padding: 8px 6px;
  text-align: left;
}

.session-title {
  display: block;
  font-size: 13px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  display: block;
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--ink-3);
}

.session-del {
  flex: none;
  width: 26px;
  height: 26px;
  color: var(--ink-3);
  font-size: 16px;
  line-height: 1;
}

/* 输入区上方的小工具条 */
.composer-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.composer-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-2);
}

.composer-icon:active {
  border-color: var(--accent);
  color: var(--accent-deep);
}
</style>
