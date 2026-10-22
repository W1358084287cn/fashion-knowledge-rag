<template>
  <div>
    <!-- 数据概览 -->
    <div class="stats-grid stats-grid-4">
      <div class="stat-box">
        <div class="stat-value">{{ overview.user_total }}</div>
        <div class="stat-label">用户数</div>
      </div>
      <div class="stat-box">
        <div class="stat-value">{{ overview.question_total }}</div>
        <div class="stat-label">提问总数</div>
      </div>
      <div class="stat-box">
        <div class="stat-value">{{ overview.hit_rate }}%</div>
        <div class="stat-label">召回命中率</div>
      </div>
      <div class="stat-box">
        <div class="stat-value">{{ overview.question_today }}</div>
        <div class="stat-label">今日提问</div>
      </div>
    </div>

    <!-- 用户列表：点击查看该用户的提问记录 -->
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">客户端用户</h2>
          <p class="section-desc">点击用户查看其提问记录、检索命中状态与召回准确度</p>
        </div>
        <button class="btn btn-sm" type="button" @click="loadUsers">刷新</button>
      </div>

      <div v-if="loadingUsers" class="empty-list">加载中…</div>
      <div v-else-if="!users.length" class="empty-list">暂无用户，请先在客户端登录演示账号</div>
      <ul v-else class="user-list">
        <li
          v-for="user in users"
          :key="user.id"
          class="user-item"
          :class="{ active: current && current.id === user.id }"
          @click="openUser(user)"
        >
          <div class="user-avatar">{{ (user.display_name || user.username).slice(0, 1) }}</div>
          <div class="user-main">
            <div class="user-line">
              <span class="user-name">{{ user.display_name }}</span>
              <span class="user-account">@{{ user.username }}</span>
            </div>
            <div class="user-line user-meta">
              提问 {{ user.question_count }} · 会话 {{ user.session_count }} ·
              平均准确度 {{ user.avg_accuracy }} 分
            </div>
            <div class="user-line user-meta">
              最近活跃：{{ user.last_active_at || user.last_login_at || '—' }}
            </div>
          </div>
          <span class="user-arrow">›</span>
        </li>
      </ul>
    </div>

    <!-- 选中用户：会话列表 -->
    <div v-if="current" class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">{{ current.display_name }} 的会话</h2>
          <p class="section-desc">共 {{ userSessions.length }} 个会话，点击查看完整对话与召回结果</p>
        </div>
        <button class="btn btn-ghost btn-sm" type="button" @click="closeUser">收起</button>
      </div>

      <div v-if="loadingSessions" class="empty-list">加载中…</div>
      <div v-else-if="!userSessions.length" class="empty-list">该用户还没有提问记录</div>
      <ul v-else class="session-pick-list">
        <li
          v-for="item in userSessions"
          :key="item.session_id"
          class="session-pick"
          :class="{ active: activeSession === item.session_id }"
          @click="openSession(item.session_id)"
        >
          <span class="session-pick-title">{{ item.title }}</span>
          <span class="session-pick-meta">{{ item.last_at }} · {{ item.message_count }} 条</span>
        </li>
      </ul>
    </div>

    <!-- 会话详情：消息 + 每次提问的检索命中与召回准确度 -->
    <div v-if="activeSession" class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">提问记录与召回准确度</h2>
          <p class="section-desc">会话 ID：{{ activeSession }}</p>
        </div>
        <button class="btn btn-ghost btn-sm" type="button" @click="activeSession = ''">收起</button>
      </div>

      <div v-if="!retrievals.length" class="empty-list">该会话暂无检索日志</div>
      <div v-else class="recall-table">
        <div class="recall-row recall-head">
          <span>提问</span><span>命中</span><span>准确度</span><span>命中片段</span><span>耗时</span>
        </div>
        <div v-for="log in retrievals" :key="log.id" class="recall-row">
          <span class="recall-question">{{ log.question }}</span>
          <span>
            <span class="status-chip" :class="log.hit ? 'done' : 'failed'">
              {{ log.hit ? '命中' : '未命中' }}
            </span>
          </span>
          <span>{{ log.accuracy }} 分（{{ log.accuracy_label }}）</span>
          <span>{{ log.doc_count }} 片段 / {{ log.triple_count }} 三元组</span>
          <span>{{ log.latency_ms }} ms</span>
        </div>
      </div>

      <h3 class="modal-subtitle">完整对话</h3>
      <div class="conversation">
        <div v-for="(msg, index) in messages" :key="index" class="conv-row" :class="msg.role">
          <span class="conv-role">{{ msg.role === 'user' ? '用户' : 'AI' }}</span>
          <div class="conv-body">
            <div class="conv-text">{{ msg.content }}</div>
            <div class="conv-time">{{ msg.created_at }}</div>
          </div>
        </div>
      </div>
    </div>

    <Toast :message="toast" :type="toastType" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { request } from '../shared/api'
import Toast from '../components/Toast.vue'

const props = defineProps({
  token: { type: String, default: '' }
})

const overview = reactive({
  user_total: 0, question_total: 0, hit_rate: 0, question_today: 0
})
const users = ref([])
const loadingUsers = ref(false)
const current = ref(null)
const userSessions = ref([])
const loadingSessions = ref(false)
const activeSession = ref('')
const messages = ref([])
const retrievals = ref([])
const toast = ref('')
const toastType = ref('info')
let toastTimer = null

function showToast(message, type = 'info') {
  toast.value = message
  toastType.value = type
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3200)
}

async function loadOverview() {
  try {
    const data = await request('/admin/overview', { token: props.token })
    Object.assign(overview, data || {})
  } catch (err) {
    // 概览失败不影响列表
  }
}

async function loadUsers() {
  loadingUsers.value = true
  try {
    const data = await request('/admin/users', { token: props.token })
    users.value = data.items || []
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    loadingUsers.value = false
  }
}

async function openUser(user) {
  current.value = user
  activeSession.value = ''
  messages.value = []
  retrievals.value = []
  loadingSessions.value = true
  try {
    const data = await request(`/admin/users/${user.id}/sessions`, { token: props.token })
    userSessions.value = data.items || []
  } catch (err) {
    showToast(err.message, 'error')
    userSessions.value = []
  } finally {
    loadingSessions.value = false
  }
}

function closeUser() {
  current.value = null
  userSessions.value = []
  activeSession.value = ''
  messages.value = []
  retrievals.value = []
}

async function openSession(sessionId) {
  activeSession.value = sessionId
  try {
    const data = await request(`/admin/sessions/${encodeURIComponent(sessionId)}/messages`, {
      token: ***
    })
    messages.value = data.items || []
    retrievals.value = data.retrievals || []
  } catch (err) {
    showToast(err.message, 'error')
  }
}

onMounted(() => {
  loadOverview()
  loadUsers()
})
</script>
