<template>
  <div class="app-shell admin-shell">
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-brand">
          <div class="brand-mark">衣</div>
          <div>
            <h1 class="login-title">管理端</h1>
            <p class="login-sub">服装多源文档智能客服系统</p>
          </div>
        </div>

        <form @submit.prevent="submit">
          <div class="field">
            <label class="field-label" for="admin-username">账号</label>
            <input
              id="admin-username"
              v-model="username"
              class="field-input"
              type="text"
              autocomplete="username"
              placeholder="请输入管理员账号"
            />
          </div>
          <div class="field">
            <label class="field-label" for="admin-password">密码</label>
            <input
              id="admin-password"
              v-model="password"
              class="field-input"
              type="password"
              autocomplete="current-password"
              placeholder="请输入密码"
            />
          </div>

          <p v-if="error" class="file-error">{{ error }}</p>

          <button class="btn btn-primary" type="submit" :disabled="loading" style="width: 100%; margin-top: 6px;">
            {{ loading ? '登录中…' : '登录' }}
          </button>
        </form>

        <p class="login-hint">演示环境已预填 <b>admin / 123456</b>，可直接点「登录」</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { request, setToken } from '../shared/api'

const emit = defineEmits(['success'])

const username = ref('admin')
const password = ref('123456')
const loading = ref(false)
const error = ref('')

async function submit() {
  if (loading.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  try {
    const data = await request('/admin/login', {
      method: 'POST',
      body: { username: username.value.trim(), password: password.value }
    })
    setToken(data.token, data.username)
    emit('success', data)
  } catch (err) {
    error.value = err.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
