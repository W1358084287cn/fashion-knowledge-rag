<template>
  <div>
    <div class="security-note">
      <span>安全说明：</span>
      <span>密钥仅保存在后端数据库，页面不会回显明文；修改后立即生效，无需重启服务。ApiKey 留空表示保持原密钥不变。</span>
    </div>

    <div v-if="loading" class="empty-list">配置加载中…</div>

    <div v-for="(agent, index) in agents" :key="agent.agent_key" class="card">
      <div class="agent-head">
        <div class="agent-index">A{{ index + 1 }}</div>
        <div>
          <h2 class="agent-name">{{ agent.agent_name }}</h2>
          <p class="agent-desc">{{ agent.description }}</p>
        </div>
      </div>

      <div class="field">
        <label class="field-label">LLM 接口 URL</label>
        <input v-model="agent.form.llm_url" class="field-input" type="text" placeholder="https://.../v1/chat/completions" />
      </div>

      <div class="field">
        <label class="field-label">
          LLM ApiKey
          <span class="key-state" :class="{ empty: !agent.llm_api_key_set }">
            · {{ agent.llm_api_key_set ? '已配置' : '未配置' }}
          </span>
        </label>
        <input
          v-model="agent.form.llm_api_key"
          class="field-input"
          type="password"
          autocomplete="new-password"
          :placeholder="agent.llm_api_key_set ? '已配置，留空则不修改' : '请输入 LLM ApiKey'"
        />
      </div>

      <div class="field">
        <label class="field-label">LLM 模型名</label>
        <input v-model="agent.form.llm_model" class="field-input" type="text" placeholder="Qwen/Qwen2.5-7B-Instruct" />
      </div>

      <div class="field">
        <label class="field-label">Embedding 接口 URL</label>
        <input v-model="agent.form.embedding_url" class="field-input" type="text" placeholder="https://.../v1/embeddings" />
      </div>

      <div class="field">
        <label class="field-label">
          Embedding ApiKey
          <span class="key-state" :class="{ empty: !agent.embedding_api_key_set }">
            · {{ agent.embedding_api_key_set ? '已配置' : '未配置' }}
          </span>
        </label>
        <input
          v-model="agent.form.embedding_api_key"
          class="field-input"
          type="password"
          autocomplete="new-password"
          :placeholder="agent.embedding_api_key_set ? '已配置，留空则不修改' : '请输入 Embedding ApiKey'"
        />
      </div>

      <div class="field">
        <label class="field-label">Embedding 模型名</label>
        <input v-model="agent.form.embedding_model" class="field-input" type="text" placeholder="BAAI/bge-m3" />
      </div>

      <div class="agent-actions">
        <button class="btn btn-primary btn-sm" type="button" :disabled="savingKey === agent.agent_key" @click="save(agent)">
          {{ savingKey === agent.agent_key ? '保存中…' : '保存' }}
        </button>
        <button class="btn btn-sm" type="button" :disabled="savingKey === agent.agent_key" @click="reset(agent)">
          重置默认配置
        </button>
        <button class="btn btn-ghost btn-sm" type="button" @click="load">刷新</button>
      </div>
      <p v-if="agent.updated_at" class="field-note">最近更新：{{ agent.updated_at }}</p>
    </div>

    <Toast :message="toast" :type="toastType" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { request } from '../shared/api'
import Toast from '../components/Toast.vue'

const props = defineProps({
  token: { type: String, default: '' }
})

const agents = ref([])
const loading = ref(false)
const savingKey = ref('')
const toast = ref('')
const toastType = ref('info')
let toastTimer = null

function showToast(message, type = 'info') {
  toast.value = message
  toastType.value = type
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = ''
  }, 3200)
}

function toForm(item) {
  return {
    llm_url: item.llm_url || '',
    llm_api_key: '',
    llm_model: item.llm_model || '',
    embedding_url: item.embedding_url || '',
    embedding_api_key: '',
    embedding_model: item.embedding_model || ''
  }
}

async function load() {
  loading.value = true
  try {
    const data = await request('/agents', { token: props.token })
    agents.value = (data || []).map((item) => ({
      ...item,
      form: toForm(item)
    }))
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    loading.value = false
  }
}

async function save(agent) {
  if (savingKey.value) return
  savingKey.value = agent.agent_key
  try {
    const data = await request(`/agents/${agent.agent_key}`, {
      method: 'PUT',
      token: ***,
      body: agent.form
    })
    // 用后端返回值刷新密钥状态；表单中的密钥输入框立即清空，避免明文停留
    agent.llm_api_key_set = ***
    agent.embedding_api_key_set = ***
    agent.updated_at = data.updated_at
    agent.form.llm_api_key = ''
    agent.form.embedding_api_key = ''
    showToast(`${agent.agent_name} 配置已保存，立即生效`)
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    savingKey.value = ''
  }
}

async function reset(agent) {
  if (savingKey.value) return
  if (!window.confirm(`确定重置「${agent.agent_name}」为默认配置吗？\n已保存的 ApiKey 会被清空。`)) return
  savingKey.value = agent.agent_key
  try {
    const data = await request(`/agents/${agent.agent_key}/reset`, {
      method: 'POST',
      token: ***
    })
    Object.assign(agent, data, { form: toForm(data) })
    showToast(`${agent.agent_name} 已重置为默认配置`)
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    savingKey.value = ''
  }
}

onMounted(load)
onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
})
</script>
