<template>
  <div>
    <!-- 知识库概览 -->
    <div class="stats-grid">
      <div class="stat-box">
        <div class="stat-value">{{ stats.file_total }}</div>
        <div class="stat-label">知识文件</div>
      </div>
      <div class="stat-box">
        <div class="stat-value">{{ stats.vector_count }}</div>
        <div class="stat-label">向量片段</div>
      </div>
      <div class="stat-box">
        <div class="stat-value">{{ stats.graph_relations }}</div>
        <div class="stat-label">图谱关系</div>
      </div>
    </div>

    <!-- 上传区 -->
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">上传知识文档</h2>
          <p class="section-desc">支持 TXT / Word / Excel / PPT / PDF / SQL / 聊天记录，无需人工清洗</p>
        </div>
        <button class="btn btn-sm" type="button" :disabled="loading" @click="loadAll">刷新</button>
      </div>

      <!-- 切片策略：三种可选，导入后自动做召回测试，不达标自动换策略重试 -->
      <div class="strategy-bar">
        <span class="strategy-label">切片策略</span>
        <button
          v-for="item in strategies"
          :key="item.value"
          class="strategy-chip"
          :class="{ active: strategy === item.value }"
          type="button"
          @click="strategy = item.value"
        >
          {{ item.label }}
        </button>
      </div>
      <p class="field-note">
        导入时不会人工清洗原始脏数据，程序会自动清洗；切片完成后自动执行检索测试，
        召回不达标会自动定位问题并切换策略重试（最多 3 轮）。
      </p>

      <!-- 小白也能看懂的切片规则说明 -->
      <div class="strategy-help">
        <div>
          <b>语义切分</b>：按句子语义递归合并，尽量保证每段意思完整，适合散文、客服话术。
        </div>
        <div>
          <b>段落切分</b>：按空行分段，段落过长时再按长度拆分，适合分点写好的文档。
        </div>
        <div>
          <b>章节切分</b>：识别「# 标题 / 第X章 / 一、 / 1.1 / 【标题】」等结构，适合手册、规范、SQL 说明。
        </div>
      </div>

      <div class="upload-zone" @click="pickFiles">
        <div class="upload-title">点击选择文件</div>
        <div class="upload-sub">可多选，单文件不超过 50MB，单次最多 10 个<br />上传后自动触发 Agent1 / Agent2 后台处理</div>
      </div>
      <input
        ref="fileInput"
        type="file"
        multiple
        hidden
        accept=".txt,.md,.docx,.pdf,.pptx,.xlsx,.xls,.csv,.json,.sql"
        @change="onPick"
      />

      <ul v-if="selected.length" class="picked-list">
        <li v-for="(file, index) in selected" :key="index">
          <span>{{ file.name }}</span>
          <span class="picked-size">{{ formatBytes(file.size) }}</span>
        </li>
      </ul>

      <div class="upload-actions">
        <button class="btn btn-primary btn-sm" type="button" :disabled="uploading || !selected.length" @click="upload">
          {{ uploading ? '上传中…' : `上传 ${selected.length || ''} 个文件` }}
        </button>
        <button class="btn btn-sm" type="button" :disabled="importing" @click="importGoods">
          {{ importing ? '导入中…' : '导入 MySQL 商品数据' }}
        </button>
        <button v-if="selected.length" class="btn btn-ghost btn-sm" type="button" @click="clearSelection">取消选择</button>
      </div>
      <p class="field-note">提示：扫描版 PDF 需安装 OCR 依赖（requirements-ocr.txt）后才能识别。</p>
    </div>

    <!-- 文件列表 -->
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">知识库文件</h2>
          <p class="section-desc">共 {{ total }} 个文件，处理状态每 3 秒自动刷新</p>
        </div>
      </div>

      <div v-if="loading && !files.length" class="empty-list">加载中…</div>
      <div v-else-if="!files.length" class="empty-list">还没有上传任何文件</div>
      <div v-else class="file-list">
        <div v-for="file in files" :key="file.id" class="file-item">
          <div class="file-top">
            <div style="min-width: 0;">
              <p class="file-name">{{ file.file_name }}</p>
              <p class="file-meta">
                {{ file.source_type }} · {{ formatBytes(file.file_size) }} · {{ file.created_at }}
              </p>
            </div>
            <span class="status-chip" :class="statusClass(file.status)">{{ statusLabel(file.status) }}</span>
          </div>

          <div v-if="isRunning(file.status)" class="progress-track">
            <div class="progress-fill" :style="{ width: `${file.progress || 0}%` }"></div>
          </div>

          <div class="badge-row">
            <span class="badge">切片策略：{{ file.chunk_strategy_label }}</span>
            <span v-if="file.chunk_count || file.triple_count" class="badge">
              片段 {{ file.chunk_count }} · 三元组 {{ file.triple_count }}
            </span>
            <span v-if="file.clean_stats && file.clean_stats.removed_chars" class="badge">
              自动清洗 {{ file.clean_stats.removed_chars }} 字符
            </span>
            <span
              v-if="file.recall_status && file.recall_status !== 'pending'"
              class="badge"
              :class="file.recall_status === 'passed' ? 'badge-ok' : (file.recall_status === 'failed' ? 'badge-bad' : '')"
            >
              召回测试 {{ recallLabel(file.recall_status) }} · {{ file.recall_score }} 分
            </span>
          </div>

          <p v-if="file.error_msg" class="file-error">{{ file.error_msg }}</p>

          <div class="file-actions">
            <button class="btn btn-sm" type="button" @click="openRaw(file)">查看源文件</button>
            <button class="btn btn-sm" type="button" @click="openChunks(file)">查看片段</button>
            <button class="btn btn-sm" type="button" @click="openRecall(file)">召回明细</button>
            <button class="btn btn-sm" type="button" :disabled="recallTesting === file.id" @click="runRecall(file)">
              {{ recallTesting === file.id ? '测试中…' : '召回测试' }}
            </button>
            <button class="btn btn-sm" type="button" @click="reprocess(file)">重新处理</button>
            <button class="btn btn-danger btn-sm" type="button" @click="remove(file)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 源文件：原文 / 自动清洗后 / 清洗明细，可下载原格式文件 -->
    <div v-if="rawFile" class="modal-mask" @click.self="closeRaw">
      <div class="modal-card modal-wide">
        <div class="section-head">
          <div>
            <h2 class="section-title">源文件 · {{ rawFile.file_name }}</h2>
            <p class="section-desc">
              类型 {{ rawData.file_type || rawFile.file_type }} ·
              当前切片策略 {{ rawData.chunk_strategy_label || rawFile.chunk_strategy_label }} ·
              可对照查看程序自动清洗前后差异
            </p>
          </div>
          <div class="header-actions">
            <a class="btn btn-sm" :href="downloadUrl(rawFile)" target="_blank" rel="noopener">下载原文件</a>
            <button class="btn btn-ghost btn-sm" type="button" @click="closeRaw">关闭</button>
          </div>
        </div>

        <div class="raw-tabs">
          <button
            v-for="tab in rawTabs"
            :key="tab.value"
            class="strategy-chip"
            :class="{ active: rawTab === tab.value }"
            type="button"
            @click="rawTab = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>

        <div v-if="rawLoading" class="empty-list">正在读取源文件…</div>

        <template v-else>
          <!-- 清洗明细 -->
          <div v-if="rawTab === 'stats'" class="clean-board">
            <div class="clean-summary">
              <div class="clean-num">
                <span class="clean-value">{{ rawData.clean_stats.original_chars || 0 }}</span>
                <span class="clean-label">清洗前字符</span>
              </div>
              <div class="clean-arrow">→</div>
              <div class="clean-num">
                <span class="clean-value">{{ rawData.clean_stats.cleaned_chars || 0 }}</span>
                <span class="clean-label">清洗后字符</span>
              </div>
              <div class="clean-num">
                <span class="clean-value danger">{{ rawData.clean_stats.removed_chars || 0 }}</span>
                <span class="clean-label">共剔除字符</span>
              </div>
            </div>

            <div class="clean-bars">
              <div v-for="row in cleanRows" :key="row.key" class="clean-bar-row">
                <span class="clean-bar-name">{{ row.label }}</span>
                <div class="clean-bar-track">
                  <div class="clean-bar-fill" :style="{ width: row.percent + '%' }"></div>
                </div>
                <span class="clean-bar-value">{{ row.value }}</span>
              </div>
            </div>

            <div v-if="cleanSamples.length" class="clean-samples">
              <p class="field-label">被剔除内容示例（程序自动识别）</p>
              <ul>
                <li v-for="(sample, index) in cleanSamples" :key="index">
                  <span class="badge">{{ sample.type }}</span>
                  <code>{{ sample.value }}</code>
                </li>
              </ul>
            </div>
            <div v-else class="empty-list">这份文件没有检测到脏数据，清洗前后内容一致</div>
          </div>

          <!-- 原文 / 清洗后 -->
          <pre v-else class="raw-text">{{ rawTab === 'original' ? rawData.original_text : rawData.cleaned_text }}</pre>
        </template>
      </div>
    </div>

    <!-- 向量片段：点击即可查看与人工修改 -->
    <div v-if="chunkFile" class="modal-mask" @click.self="closeChunks">
      <div class="modal-card">
        <div class="section-head">
          <div>
            <h2 class="section-title">向量片段 · {{ chunkFile.file_name }}</h2>
            <p class="section-desc">
              共 {{ chunks.length }} 个片段 ·
              当前策略 {{ chunkFile.chunk_strategy_label || '语义切分' }}（{{ strategyTip(chunkFile.chunk_strategy) }}）·
              修改后自动重建向量，立即影响检索
            </p>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="closeChunks">关闭</button>
        </div>

        <div v-if="chunksLoading" class="empty-list">加载中…</div>
        <div v-else-if="!chunks.length" class="empty-list">该文件暂无片段</div>
        <ul v-else class="chunk-list">
          <li v-for="chunk in chunks" :key="chunk.id" class="chunk-item">
            <div class="chunk-head">
              <span class="badge">#{{ chunk.chunk_index + 1 }}</span>
              <span class="badge" v-if="chunk.category">{{ chunk.category }}</span>
              <span class="badge" v-if="chunk.goods_no">{{ chunk.goods_no }}</span>
              <span class="chunk-len">{{ chunk.text.length }} 字</span>
              <div class="chunk-btns">
                <button class="btn btn-sm" type="button" @click="editChunk(chunk)">
                  {{ editingId === chunk.id ? '收起' : '修改' }}
                </button>
                <button class="btn btn-danger btn-sm" type="button" @click="deleteChunk(chunk)">删除</button>
              </div>
            </div>
            <div v-if="editingId !== chunk.id" class="chunk-text">{{ chunk.text }}</div>
            <div v-else class="chunk-editor">
              <textarea v-model="chunk.draft" class="field-textarea" rows="6"></textarea>
              <div class="upload-actions">
                <button class="btn btn-primary btn-sm" type="button" :disabled="savingChunk" @click="saveChunk(chunk)">
                  {{ savingChunk ? '保存中…' : '保存并重建向量' }}
                </button>
                <button class="btn btn-sm" type="button" @click="cancelEdit(chunk)">取消</button>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <!-- 召回测试明细 -->
    <div v-if="recallFile" class="modal-mask" @click.self="closeRecall">
      <div class="modal-card">
        <div class="section-head">
          <div>
            <h2 class="section-title">召回测试 · {{ recallFile.file_name }}</h2>
            <p class="section-desc">
              当前策略 {{ recallData.strategy_label || '—' }} · 准确度 {{ recallData.score || 0 }} 分 ·
              {{ recallLabel(recallData.status) }}
            </p>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="closeRecall">关闭</button>
        </div>

        <div v-if="recallLoading" class="empty-list">加载中…</div>
        <div v-else-if="!recallData.items || !recallData.items.length" class="empty-list">
          还没有测试记录，可点击「召回测试」发起一次
        </div>
        <ul v-else class="chunk-list">
          <li v-for="(item, index) in recallData.items" :key="index" class="chunk-item">
            <div class="chunk-head">
              <span class="badge">第 {{ item.iteration }} 轮 · {{ item.strategy_label }}</span>
              <span class="status-chip" :class="item.hit ? 'done' : 'failed'">
                {{ item.hit ? '命中' : '未命中' }}
              </span>
              <span class="chunk-len">重合度 {{ item.score }}</span>
            </div>
            <div class="chunk-text">{{ item.question }}</div>
          </li>
        </ul>
      </div>
    </div>

    <Toast :message="toast" :type="toastType" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { request } from '../shared/api'
import Toast from '../components/Toast.vue'
import {
  RUNNING_STATUS,
  formatBytes,
  statusClass,
  statusLabel
} from '../shared/format'

const props = defineProps({
  token: { type: String, default: '' }
})

const strategies = [
  { value: 'semantic', label: '语义切分' },
  { value: 'paragraph', label: '段落切分' },
  { value: 'chapter', label: '章节切分' }
]

const fileInput = ref(null)
const selected = ref([])
const files = ref([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const importing = ref(false)
const strategy = ref('semantic')
const stats = reactive({ file_total: 0, vector_count: 0, graph_relations: 0 })

// 片段查看/编辑
const chunkFile = ref(null)
const chunks = ref([])
const chunksLoading = ref(false)
const editingId = ref('')
const savingChunk = ref(false)

// 召回测试
const recallFile = ref(null)
const recallData = reactive({ status: 'pending', score: 0, strategy_label: '', items: [] })
const recallLoading = ref(false)
const recallTesting = ref(0)

const toast = ref('')
const toastType = ref('info')
let toastTimer = null
let pollTimer = null

function showToast(message, type = 'info') {
  toast.value = message
  toastType.value = type
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3200)
}

function isRunning(status) {
  return RUNNING_STATUS.includes(status)
}

function recallLabel(status) {
  if (status === 'passed') return '通过'
  if (status === 'failed') return '未通过'
  if (status === 'running') return '测试中'
  return '待测试'
}

function pickFiles() {
  if (fileInput.value) fileInput.value.click()
}

function onPick(event) {
  selected.value = Array.from(event.target.files || [])
  event.target.value = ''
}

function clearSelection() {
  selected.value = []
}

async function loadAll() {
  await Promise.all([loadFiles(), loadStats()])
}

async function loadFiles() {
  loading.value = true
  try {
    const data = await request(`/kb/files?page=1&page_size=50`, { token: props.token })
    files.value = data.items || []
    total.value = data.total || 0
  } catch (err) {
    if (!files.value.length) showToast(err.message, 'error')
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const data = await request('/kb/stats', { token: props.token })
    stats.file_total = data.file_total || 0
    stats.vector_count = data.vector_count || 0
    stats.graph_relations = data.graph_relations || 0
  } catch (err) {
    // 统计失败不影响主流程
  }
}

/** 多文件上传（携带所选切片策略） */
async function upload() {
  if (!selected.value.length || uploading.value) return
  const form = new FormData()
  selected.value.forEach((file) => form.append('files', file))
  form.append('strategy', strategy.value)
  uploading.value = true
  try {
    const data = await request('/kb/upload', {
      method: 'POST',
      body: form,
      token: ***,
      timeout: 120000
    })
    const success = (data.items || []).length
    const errors = data.errors || []
    if (errors.length) {
      showToast(`成功 ${success} 个，失败 ${errors.length} 个：${errors[0].file_name} ${errors[0].error}`, 'error')
    } else {
      showToast(`已上传 ${success} 个文件，后台正在处理并自动测试召回`)
    }
    selected.value = []
    await loadAll()
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    uploading.value = false
  }
}

/** 导入 MySQL 商品结构化数据 */
async function importGoods() {
  if (importing.value) return
  importing.value = true
  try {
    const data = await request(`/kb/import-goods?strategy=${strategy.value}`, {
      method: 'POST', token: props.token
    })
    showToast(`已导入商品数据：${data.file_name}`)
    await loadAll()
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    importing.value = false
  }
}

async function reprocess(file) {
  try {
    await request(`/kb/files/${file.id}/reprocess?strategy=${strategy.value}`, {
      method: 'POST', token: props.token
    })
    showToast(`已按「${strategyLabel(strategy.value)}」重新提交处理`)
    await loadAll()
  } catch (err) {
    showToast(err.message, 'error')
  }
}

function strategyLabel(value) {
  const item = strategies.find((s) => s.value === value)
  return item ? item.label : value
}

async function remove(file) {
  if (!window.confirm(`确定删除「${file.file_name}」吗？\n该文件对应的向量与图谱数据会一并清理。`)) return
  try {
    const data = await request(`/kb/files/${file.id}`, { method: 'DELETE', token: props.token })
    const warning = data && data.warnings && data.warnings.length ? data.warnings[0] : ''
    showToast(warning ? `已删除，但${warning}` : '已删除', warning ? 'error' : 'info')
    await loadAll()
  } catch (err) {
    showToast(err.message, 'error')
  }
}

// 源文件查看（原文 / 清洗后 / 清洗明细）
const rawFile = ref(null)
const rawLoading = ref(false)
const rawTab = ref('original')
const rawTabs = [
  { value: 'original', label: '原始内容' },
  { value: 'cleaned', label: '自动清洗后' },
  { value: 'stats', label: '清洗明细' }
]
const rawData = reactive({
  file_type: '',
  source_type: '',
  original_text: '',
  cleaned_text: '',
  chunk_strategy_label: '',
  clean_stats: {}
})

// 清洗统计条形图（按数量排序，百分比相对最大值）
const cleanRows = computed(() => {
  const s = rawData.clean_stats || {}
  const rows = [
    { key: 'url_count', label: 'URL 链接', value: s.url_count || 0 },
    { key: 'email_count', label: '邮箱地址', value: s.email_count || 0 },
    { key: 'control_count', label: '控制字符', value: s.control_count || 0 },
    { key: 'page_number_lines', label: '页码行', value: s.page_number_lines || 0 },
    { key: 'separator_lines', label: '分隔线', value: s.separator_lines || 0 },
    { key: 'duplicate_lines', label: '重复行', value: s.duplicate_lines || 0 },
    { key: 'blank_lines', label: '空行', value: s.blank_lines || 0 }
  ]
  const max = Math.max(1, ...rows.map((r) => r.value))
  return rows.map((r) => ({ ...r, percent: Math.round((r.value / max) * 100) }))
})

// 被剔除内容示例（程序自动识别到的脏数据）
const cleanSamples = computed(() => {
  const samples = (rawData.clean_stats && rawData.clean_stats.samples) || {}
  const labels = {
    url: 'URL',
    email: '邮箱',
    page_number: '页码',
    separator: '分隔线',
    duplicate: '重复行',
    html: 'HTML 标签'
  }
  const list = []
  Object.keys(samples).forEach((key) => {
    (samples[key] || []).forEach((value) => {
      list.push({ type: labels[key] || key, value })
    })
  })
  return list
})

function strategyTip(value) {
  if (value === 'paragraph') return '按空行分段，超长再拆'
  if (value === 'chapter') return '识别标题/章节结构'
  return '按语义递归合并完整句子'
}

function downloadUrl(file) {
  return `/api/kb/files/${file.id}/download?token=${encodeURIComponent(props.token)}`
}

async function openRaw(file) {
  rawFile.value = file
  rawTab.value = 'original'
  rawLoading.value = true
  rawData.original_text = ''
  rawData.cleaned_text = ''
  rawData.clean_stats = {}
  try {
    const data = await request(`/kb/files/${file.id}/raw`, { token: props.token, timeout: 60000 })
    rawData.file_type = data.file_type || ''
    rawData.source_type = data.source_type || ''
    rawData.original_text = data.original_text || ''
    rawData.cleaned_text = data.cleaned_text || ''
    rawData.clean_stats = data.clean_stats || {}
    rawData.chunk_strategy_label = data.chunk_strategy_label || ''
  } catch (err) {
    showToast(err.message, 'error')
    rawFile.value = null
  } finally {
    rawLoading.value = false
  }
}

function closeRaw() {
  rawFile.value = null
  rawData.original_text = ''
  rawData.cleaned_text = ''
  rawData.clean_stats = {}
}

/** ---------- 向量片段：查看 / 修改 / 删除 ---------- */
async function openChunks(file) {
  chunkFile.value = file
  chunks.value = []
  editingId.value = ''
  chunksLoading.value = true
  try {
    const data = await request(`/kb/files/${file.id}/chunks`, { token: props.token })
    chunks.value = (data.items || []).map((item) => ({ ...item, draft: item.text }))
  } catch (err) {
    showToast(err.message, 'error')
    chunkFile.value = null
  } finally {
    chunksLoading.value = false
  }
}

function closeChunks() {
  chunkFile.value = null
  chunks.value = []
  editingId.value = ''
}

function editChunk(chunk) {
  editingId.value = editingId.value === chunk.id ? '' : chunk.id
  chunk.draft = chunk.text
}

function cancelEdit(chunk) {
  chunk.draft = chunk.text
  editingId.value = ''
}

async function saveChunk(chunk) {
  if (savingChunk.value) return
  const text = String(chunk.draft || '').trim()
  if (!text) {
    showToast('片段内容不能为空', 'error')
    return
  }
  savingChunk.value = true
  try {
    await request(`/kb/files/${chunkFile.value.id}/chunks/${chunk.id}`, {
      method: 'PUT',
      token: ***,
      body: { text, category: chunk.category, goods_no: chunk.goods_no }
    })
    chunk.text = text
    chunk.draft = text
    editingId.value = ''
    showToast('片段已更新，向量已同步重建')
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    savingChunk.value = false
  }
}

async function deleteChunk(chunk) {
  if (!window.confirm('确定删除该片段吗？删除后不再参与检索。')) return
  try {
    await request(`/kb/files/${chunkFile.value.id}/chunks/${chunk.id}`, {
      method: 'DELETE', token: props.token
    })
    chunks.value = chunks.value.filter((item) => item.id !== chunk.id)
    showToast('片段已删除')
    loadStats()
  } catch (err) {
    showToast(err.message, 'error')
  }
}

/** ---------- 召回测试 ---------- */
async function runRecall(file) {
  recallTesting.value = file.id
  try {
    await request(`/kb/files/${file.id}/recall-test`, { method: 'POST', token: props.token })
    showToast('召回测试已开始，完成后会自动刷新结果')
    // 轮询文件，测试结束后自动打开明细
    let counter = 0
    const timer = setInterval(async () => {
      counter += 1
      await loadFiles()
      const latest = files.value.find((item) => item.id === file.id)
      if ((!latest || latest.recall_status !== 'running') || counter >= 30) {
        clearInterval(timer)
        recallTesting.value = 0
        if (latest) openRecall(latest)
      }
    }, 2000)
  } catch (err) {
    showToast(err.message, 'error')
    recallTesting.value = 0
  }
}

async function openRecall(file) {
  recallFile.value = file
  recallLoading.value = true
  try {
    const data = await request(`/kb/files/${file.id}/recall`, { token: props.token })
    recallData.status = data.status
    recallData.score = data.score
    recallData.strategy_label = data.chunk_strategy_label || ''
    recallData.items = data.items || []
  } catch (err) {
    showToast(err.message, 'error')
    recallData.items = []
  } finally {
    recallLoading.value = false
  }
}

function closeRecall() {
  recallFile.value = null
  recallData.items = []
}

onMounted(() => {
  loadAll()
  pollTimer = setInterval(() => {
    loadFiles()
    loadStats()
  }, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>
