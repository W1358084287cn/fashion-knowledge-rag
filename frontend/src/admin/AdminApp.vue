<template>
  <LoginView v-if="!token" @success="onLogin" />

  <div v-else class="app-shell admin-shell">
    <header class="admin-header">
      <div class="brand">
        <div class="brand-mark">衣</div>
        <div>
          <h1 class="brand-title">智能客服管理端</h1>
          <p class="brand-sub">{{ username }} · 知识库 · 用户 · 日志</p>
        </div>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" @click="logout">退出</button>
    </header>

    <main class="admin-main">
      <KbTab v-if="activeTab === 'kb'" :token="token" />
      <GraphTab v-else-if="activeTab === 'graph'" :token="token" />
      <VectorTab v-else-if="activeTab === 'vector'" :token="token" />
      <UsersTab v-else-if="activeTab === 'users'" :token="token" />
      <LogsTab v-else-if="activeTab === 'logs'" :token="token" />
      <AgentsTab v-else-if="activeTab === 'agents'" :token="token" />
      <ChatTab v-else :token="token" />
    </main>

    <!-- 七个 Tab：知识库 / 图谱 / 向量库 / 用户 / 日志 / Agent 配置 / 对话测试 -->
    <nav class="bottom-nav nav-7">
      <button class="nav-item" :class="{ active: activeTab === 'kb' }" type="button" @click="activeTab = 'kb'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M4 6.5C4 5.12 5.12 4 6.5 4H20V18H6.5C5.12 18 4 19.12 4 20.5V6.5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
            <path d="M4 17.5C4 16.12 5.12 15 6.5 15H20" stroke="currentColor" stroke-width="1.7" />
          </svg>
        </span>
        知识库
      </button>
      <button class="nav-item" :class="{ active: activeTab === 'vector' }" type="button" @click="activeTab = 'vector'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="4" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.6" />
            <rect x="14" y="4" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.6" />
            <rect x="4" y="14" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.6" />
            <rect x="14" y="14" width="6" height="6" rx="1.4" stroke="currentColor" stroke-width="1.6" />
            <path d="M10 7H14M7 10V14M17 10V14M10 17H14" stroke="currentColor" stroke-width="1.5" />
          </svg>
        </span>
        向量库
      </button>
      <button class="nav-item" :class="{ active: activeTab === 'graph' }" type="button" @click="activeTab = 'graph'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <circle cx="6" cy="7" r="2.4" stroke="currentColor" stroke-width="1.7" />
            <circle cx="18" cy="6" r="2.4" stroke="currentColor" stroke-width="1.7" />
            <circle cx="12" cy="18" r="2.4" stroke="currentColor" stroke-width="1.7" />
            <path d="M8.2 7.4L15.6 6.3M7.4 9.2L10.8 15.8M16.5 8.1L13.3 15.7" stroke="currentColor" stroke-width="1.5" />
          </svg>
        </span>
        图谱
      </button>
      <button class="nav-item" :class="{ active: activeTab === 'users' }" type="button" @click="activeTab = 'users'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="8" r="3.4" stroke="currentColor" stroke-width="1.7" />
            <path d="M5 20C5 16.4 8.1 14 12 14C15.9 14 19 16.4 19 20" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
          </svg>
        </span>
        用户
      </button>
      <button class="nav-item" :class="{ active: activeTab === 'logs' }" type="button" @click="activeTab = 'logs'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M6 4H18V20H6V4Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
            <path d="M9 8H15M9 12H15M9 16H13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </span>
        日志
      </button>
      <button class="nav-item" :class="{ active: activeTab === 'agents' }" type="button" @click="activeTab = 'agents'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M5 7H19M5 12H19M5 17H19" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <circle cx="9" cy="7" r="2.2" fill="var(--bg)" stroke="currentColor" stroke-width="1.6" />
            <circle cx="15" cy="12" r="2.2" fill="var(--bg)" stroke="currentColor" stroke-width="1.6" />
            <circle cx="8" cy="17" r="2.2" fill="var(--bg)" stroke="currentColor" stroke-width="1.6" />
          </svg>
        </span>
        Agent
      </button>
      <button class="nav-item" :class="{ active: activeTab === 'chat' }" type="button" @click="activeTab = 'chat'">
        <span class="nav-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M5 5H19C20.1 5 21 5.9 21 7V15C21 16.1 20.1 17 19 17H9L5 20V17H5C3.9 17 3 16.1 3 15V7C3 5.9 3.9 5 5 5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
            <path d="M8 10H16M8 13H13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </span>
        对话
      </button>
    </nav>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import LoginView from './LoginView.vue'
import KbTab from './KbTab.vue'
import GraphTab from './GraphTab.vue'
import VectorTab from './VectorTab.vue'
import UsersTab from './UsersTab.vue'
import LogsTab from './LogsTab.vue'
import AgentsTab from './AgentsTab.vue'
import ChatTab from './ChatTab.vue'
import { clearToken, getAdminName, getToken, request } from '../shared/api'

const token = ref(getToken())
const username = ref(getAdminName())
const activeTab = ref('kb')

function onLogin(data) {
  token.value = ***
  username.value = data.username || 'admin'
  activeTab.value = 'kb'
}

function logout() {
  clearToken()
  token.value = ''
}

function onUnauthorized() {
  logout()
}

async function verifyToken() {
  if (!token.value) return
  try {
    await request('/admin/me', { token: token.value, timeout: 8000 })
  } catch (err) {
    if (err.code === 1002) logout()
  }
}

onMounted(() => {
  verifyToken()
  window.addEventListener('admin-unauthorized', onUnauthorized)
})

onBeforeUnmount(() => {
  window.removeEventListener('admin-unauthorized', onUnauthorized)
})
</script>
