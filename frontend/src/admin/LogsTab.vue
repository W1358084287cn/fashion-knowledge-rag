<template>
  <div>
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">检索日志</h2>
          <p class="section-desc">每次提问的命中状态、召回准确度、召回片段数与耗时</p>
        </div>
        <button class="btn btn-sm" type="button" @click="loadLogs">刷新</button>
      </div>

      <div class="filter-bar">
        <select v-model="level" class="field-input filter-input" @change="reload">
          <option value="">全部等级</option>
          <option value="high">高（≥95 分）</option>
          <option value="medium">中（80 分）</option>
          <option value="low">低（60 分）</option>
          <option value="miss">未命中</option>
        </select>
        <input
          v-model="keyword"
          class="field-input filter-input"
          type="text"
          placeholder="按提问关键词搜索"
          @keydown.enter="reload"
        />
        <button class="btn btn-sm" type="button" @click="reload">查询</button>
      </div>

      <div v-if="loading" class="empty-list">加载中…</div>
      <div v-else-if="!logs.length" class="empty-list">暂无检索日志</div>
      <ul v-else class="log-list">
        <li v-for="log in logs" :key="log.id" class="log-item">
          <div class="log-top">
            <span class="log-question">{{ log.question }}</span>
            <span class="status-chip" :class="log.hit ? 'done' : 'failed'">
              {{ log.hit ? '命中' : '未命中' }}
            </span>
          </div>
          <div class="log-meta">
            {{ log.username }}（{{ log.user_type }}） · {{ log.accuracy }} 分（{{ log.accuracy_label }}）
            · {{ log.doc_count }} 片段 / {{ log.triple_count }} 三元组
            · 最高相似度 {{ log.top_score }} · {{ log.latency_ms }} ms
          </div>
          <div class="log-meta">{{ log.created_at }} · 会话 {{ log.session_id }}</div>
        </li>
      </ul>

      <div class="pager">
        <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="turn(-1)">上一页</button>
        <span class="pager-text">第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button class="btn btn-sm" type="button" :disabled="page * pageSize >= total" @click="turn(1)">下一页</button>
      </div>
    </div>

    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">操作日志</h2>
          <p class="section-desc">登录、上传、重处理、删除、配置修改等操作全量留存</p>
        </div>
      </div>

      <div class="filter-bar">
        <select v-model="actorType" class="field-input filter-input" @change="reloadOps">
          <option value="">全部操作人</option>
          <option value="admin">管理员</option>
          <option value="user">普通用户</option>
        </select>
        <input
          v-model="opKeyword"
          class="field-input filter-input"
          type="text"
          placeholder="按操作 / 对象 / 操作人搜索"
          @keydown.enter="reloadOps"
        />
        <button class="btn btn-sm" type="button" @click="reloadOps">查询</button>
      </div>

      <div v-if="opLoading" class="empty-list">加载中…</div>
      <div v-else-if="!ops.length" class="empty-list">暂无操作日志</div>
      <ul v-else class="log-list">
        <li v-for="op in ops" :key="op.id" class="log-item">
          <div class="log-top">
            <span class="log-question">{{ op.action }}</span>
            <span class="status-chip">{{ op.actor_type === 'admin' ? '管理员' : '用户' }}</span>
          </div>
          <div class="log-meta">{{ op.actor }} · {{ op.target || '—' }}</div>
          <div v-if="op.detail" class="log-meta">{{ op.detail }}</div>
          <div class="log-meta">{{ op.created_at }} · IP {{ op.ip || '—' }}</div>
        </li>
      </ul>

      <div class="pager">
        <button class="btn btn-sm" type="button" :disabled="opPage <= 1" @click="turnOps(-1)">上一页</button>
        <span class="pager-text">第 {{ opPage }} 页 · 共 {{ opTotal }} 条</span>
        <button class="btn btn-sm" type="button" :disabled="opPage * pageSize >= opTotal" @click="turnOps(1)">下一页</button>
      </div>
    </div>

    <Toast :message="toast" :type="toastType" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { request } from '../shared/api'
import Toast from '../components/Toast.vue'

const props = defineProps({
  token: { type: String, default: '' }
})

const pageSize = 20
const level = ref('')
const keyword = ref('')
const logs = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

const actorType = ref('')
const opKeyword = ref('')
const ops = ref([])
const opTotal = ref(0)
const opPage = ref(1)
const opLoading = ref(false)

const toast = ref('')
const toastType = ref('info')

function showToast(message, type = 'info') {
  toast.value = message
  toastType.value = type
  setTimeout(() => { toast.value = '' }, 3000)
}

async function loadLogs() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      page_size: String(pageSize)
    })
    if (level.value) params.set('level', level.value)
    if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
    const data = await request(`/admin/retrieval-logs?${params.toString()}`, { token: props.token })
    logs.value = data.items || []
    total.value = data.total || 0
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    loading.value = false
  }
}

async function loadOps() {
  opLoading.value = true
  try {
    const params = new URLSearchParams({
      page: String(opPage.value),
      page_size: String(pageSize)
    })
    if (actorType.value) params.set('actor_type', actorType.value)
    if (opKeyword.value.trim()) params.set('keyword', opKeyword.value.trim())
    const data = await request(`/admin/operation-logs?${params.toString()}`, { token: props.token })
    ops.value = data.items || []
    opTotal.value = data.total || 0
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    opLoading.value = false
  }
}

function reload() {
  page.value = 1
  loadLogs()
}

function turn(step) {
  page.value += step
  loadLogs()
}

function reloadOps() {
  opPage.value = 1
  loadOps()
}

function turnOps(step) {
  opPage.value += step
  loadOps()
}

onMounted(() => {
  loadLogs()
  loadOps()
})
</script>
