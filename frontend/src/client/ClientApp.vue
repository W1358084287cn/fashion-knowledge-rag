<template>
  <!-- 未登录：演示账号已预填，一键登录后即可提问 -->
  <div v-if="!token" class="app-shell">
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-brand">
          <div class="brand-mark">衣</div>
          <div>
            <h1 class="login-title">衣尚智能客服</h1>
            <p class="login-sub">服装多源文档智能问答</p>
          </div>
        </div>

        <form @submit.prevent="login">
          <div class="field">
            <label class="field-label" for="user-username">账号</label>
            <input
              id="user-username"
              v-model="username"
              class="field-input"
              type="text"
              autocomplete="username"
            />
          </div>
          <div class="field">
            <label class="field-label" for="user-password">密码</label>
            <input
              id="user-password"
              v-model="password"
              class="field-input"
              type="password"
              autocomplete="current-password"
            />
          </div>

          <p v-if="error" class="file-error">{{ error }}</p>

          <button class="btn btn-primary" type="submit" :disabled="loading" style="width: 100%; margin-top: 6px;">
            {{ loading ? '登录中…' : '一键登录' }}
          </button>
        </form>

        <p class="login-hint">演示账号 demo · 密码 123456（已自动填入，直接点击登录）</p>
      </div>
    </div>
  </div>

  <!-- 已登录：客户端聊天 -->
  <div v-else class="app-shell">
    <header class="chat-header">
      <div class="brand">
        <div class="brand-mark">衣</div>
        <div>
          <h1 class="brand-title">衣尚智能客服</h1>
          <p class="brand-sub"><span class="live-dot"></span>{{ userName || '演示用户' }} · 在线</p>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn btn-ghost btn-sm" type="button" @click="panel && panel.startNewChat()">新对话</button>
        <button class="btn btn-ghost btn-sm" type="button" @click="logout">退出</button>
      </div>
    </header>

    <!-- identity 变化时重建面板，避免上一个账号的历史串到新账号 -->
    <ChatPanel ref="panel" mode="client" :token="token" :identity="identity" :scope="userId || 'default'" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'
import {
  clearUserSession, getUserId, getUserName, getUserToken, request, setUserSession
} from '../shared/api'

const panel = ref(null)
const token = ref(getUserToken())
const userName = ref(getUserName())
const userId = ref(getUserId())

// 演示账号：登录页自动预填，点击「一键登录」即可进入
const username = ref('demo')
const password = ref('123456')
const loading = ref(false)
const error = ref('')

const identity = computed(() => `${userName.value}-${token.value.slice(-8)}`)

async function login() {
  if (loading.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  try {
    const data = await request('/user/login', {
      method: 'POST',
      body: { username: username.value.trim(), password: password.value }
    })
    setUserSession(data)
    token.value = ***
    userName.value = data.display_name || data.username
    userId.value = String(data.user_id || '')
    error.value = ''
  } catch (err) {
    error.value = err.message || '登录失败'
  } finally {
    loading.value = false
  }
}

function logout() {
  clearUserSession()
  token.value = ''
  userName.value = ''
  userId.value = ''
}
</script>

<style scoped>
.header-actions {
  display: flex;
  gap: 2px;
  flex: none;
}
</style>
