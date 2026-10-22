<template>
  <div>
    <!-- 向量库概览：把 Qdrant 的状态用图形化卡片讲清楚 -->
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">向量数据库 · 图形化看板</h2>
          <p class="section-desc">
            集合 {{ overview.collection }} · 共 {{ overview.points }} 个向量片段，
            可直接在下方输入一句话查看检索到底召回了什么
          </p>
        </div>
        <button class="btn btn-sm" type="button" :disabled="loading" @click="loadOverview">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>

      <div class="vector-cards">
        <div class="vector-card">
          <span class="vector-card-label">向量条数</span>
          <span class="vector-card-value">{{ overview.points }}</span>
          <span class="vector-card-note">已入库切片总量</span>
        </div>
        <div class="vector-card">
          <span class="vector-card-label">向量维度</span>
          <span class="vector-card-value">{{ overview.dim }}</span>
          <span class="vector-card-note">稠密向量维度</span>
        </div>
        <div class="vector-card">
          <span class="vector-card-label">距离度量</span>
          <span class="vector-card-value small">{{ overview.distance }}</span>
          <span class="vector-card-note">余弦相似度</span>
        </div>
        <div class="vector-card">
          <span class="vector-card-label">集合状态</span>
          <span class="vector-card-value small" :class="overview.exists ? 'ok' : 'danger'">
            {{ overview.exists ? '正常' : '未创建' }}
          </span>
          <span class="vector-card-note">Qdrant 集合</span>
        </div>
      </div>

      <div class="vector-grid">
        <div>
          <p class="field-label">片段分布 · 按文件</p>
          <div v-if="!overview.files.length" class="empty-list">暂无片段</div>
          <div v-else class="stat-bars">
            <div v-for="row in overview.files" :key="row.name" class="stat-bar-row">
              <span class="stat-bar-name" :title="row.name">{{ row.name }}</span>
              <div class="stat-bar-track">
                <div class="stat-bar-fill" :style="{ width: barPercent(row.count, overview.files) + '%' }"></div>
              </div>
              <span class="stat-bar-value">{{ row.count }}</span>
            </div>
          </div>
        </div>
        <div>
          <p class="field-label">片段分布 · 按分类</p>
          <div v-if="!overview.categories.length" class="empty-list">暂无分类数据</div>
          <div v-else class="stat-bars">
            <div v-for="row in overview.categories" :key="row.name" class="stat-bar-row">
              <span class="stat-bar-name">{{ row.name }}</span>
              <div class="stat-bar-track">
                <div class="stat-bar-fill alt" :style="{ width: barPercent(row.count, overview.categories) + '%' }"></div>
              </div>
              <span class="stat-bar-value">{{ row.count }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="overview.index_fields.length" class="vector-index">
        <p class="field-label">payload 索引字段（用于按分类 / 款号 / 文件过滤检索）</p>
        <div class="badge-row">
          <span v-for="field in overview.index_fields" :key="field.field" class="badge">
            {{ field.field }} · {{ field.type }}
          </span>
        </div>
      </div>
    </div>

    <!-- 图形化检索：不用写代码，输入一句话就能看召回结果 -->
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">向量检索实验台</h2>
          <p class="section-desc">输入问题即可看到相似片段、相似度与来源，方便验证知识库是否真的能召回</p>
        </div>
      </div>

      <div class="vector-search">
        <input
          v-model="query"
          class="filter-input"
          type="text"
          placeholder="例如：羊毛大衣怎么保养？"
          @keyup.enter="search"
        />
        <select v-model.number="topK" class="filter-input filter-select">
          <option :value="5">Top 5</option>
          <option :value="8">Top 8</option>
          <option :value="12">Top 12</option>
        </select>
        <select v-model="fileFilter" class="filter-input filter-select">
          <option value="">全部文件</option>
          <option v-for="item in fileOptions" :key="item.id" :value="item.id">{{ item.file_name }}</option>
        </select>
        <button class="btn btn-primary btn-sm" type="button" :disabled="searching" @click="search">
          {{ searching ? '检索中…' : '开始检索' }}
        </button>
      </div>

      <!-- 小白不会提问时，点一下示例即可直接检索 -->
      <div class="vector-examples">
        <span class="vector-examples-label">试试这些：</span>
        <button
          v-for="item in examples"
          :key="item"
          class="graph-type-chip"
          type="button"
          @click="useExample(item)"
        >{{ item }}</button>
      </div>

      <div v-if="searchError" class="file-error">{{ searchError }}</div>
      <div v-if="!results.length && searched && !searching" class="empty-list">
        没有召回任何片段，可换一句话或先导入知识文件
      </div>

      <ul v-if="results.length" class="vector-result-list">
        <li v-for="item in results" :key="item.id + '-' + item.rank" class="vector-result">
          <div class="vector-result-head">
            <span class="badge">#{{ item.rank }}</span>
            <span class="badge" v-if="item.category">{{ item.category }}</span>
            <span class="badge" v-if="item.goods_no">{{ item.goods_no }}</span>
            <span class="vector-result-file">{{ item.file_name }} · 片段 {{ item.chunk_index + 1 }}</span>
            <span class="vector-result-score">{{ (matchPercent(item) * 100).toFixed(1) }}%</span>
          </div>
          <div class="vector-score-track">
            <div class="vector-score-fill" :style="{ width: Math.max(2, matchPercent(item) * 100) + '%' }"></div>
          </div>
          <div class="vector-result-note">
            综合匹配度（首位为 100%）· 稠密相似度 {{ (item.similarity * 100).toFixed(1) }}%
          </div>
          <div class="chunk-text compact">{{ item.text }}</div>
        </li>
      </ul>
    </div>

    <Toast :message="toast" :type="toastType" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { request } from '../shared/api'
import Toast from '../components/Toast.vue'

const props = defineProps({
  token: { type: String, default: '' }
})

const loading = ref(false)
const searching = ref(false)
const searched = ref(false)
const query = ref('')
const topK = ref(8)
const fileFilter = ref('')
const results = ref([])
const searchError = ref('')
const toast = ref('')
const toastType = ref('info')

// 常见提问示例：降低小白使用门槛
const examples = ['羊毛大衣怎么保养', '退换货运费谁承担', '尺码偏大还是偏小']

function useExample(text) {
  query.value = text
  search()
}

const overview = reactive({
  collection: 'fashion_knowledge',
  exists: false,
  points: 0,
  dim: 1024,
  distance: 'Cosine',
  index_fields: [],
  files: [],
  categories: [],
  source_types: []
})

// 文件下拉选项来自知识库文件列表（带 id，便于按文件过滤）
const kbFiles = ref([])
const fileOptions = computed(() => kbFiles.value)

function showToast(message, type = 'info') {
  toast.value = message
  toastType.value = type
  setTimeout(() => { toast.value = '' }, 3000)
}

function barPercent(count, rows) {
  const max = Math.max(1, ...rows.map((row) => row.count))
  return Math.max(3, Math.round((count / max) * 100))
}

// 后端返回的 match 为 RRF 综合分归一化结果，首条固定 100%，与名次顺序一致
function matchPercent(item) {
  return Number(item.match ?? item.similarity ?? 0)
}

async function loadOverview() {
  loading.value = true
  try {
    const data = await request('/kb/vector-overview', { token: props.token })
    Object.assign(overview, data, {
      index_fields: data.index_fields || [],
      files: data.files || [],
      categories: data.categories || [],
      source_types: data.source_types || []
    })
  } catch (err) {
    showToast(err.message, 'error')
  } finally {
    loading.value = false
  }
}

async function loadFiles() {
  try {
    const data = await request('/kb/files?page=1&page_size=50', { token: props.token })
    kbFiles.value = data.items || []
  } catch (err) {
    // 文件列表失败不影响看板
  }
}

async function search() {
  const text = query.value.trim()
  if (!text) {
    showToast('请输入检索内容', 'error')
    return
  }
  searching.value = true
  searchError.value = ''
  try {
    const data = await request('/kb/search', {
      method: 'POST',
      token: ***,
      body: {
        query: text,
        top_k: topK.value,
        file_id: fileFilter.value ? Number(fileFilter.value) : undefined
      }
    })
    results.value = data.items || []
    searched.value = true
  } catch (err) {
    searchError.value = err.message
    results.value = []
    searched.value = true
  } finally {
    searching.value = false
  }
}

onMounted(() => {
  loadOverview()
  loadFiles()
})
</script>
