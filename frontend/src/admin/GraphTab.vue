<template>
  <div>
    <div class="card">
      <div class="section-head">
        <div>
          <h2 class="section-title">知识图谱 · 可视化操作</h2>
          <p class="section-desc">
            共 {{ allNodes.length }} 个实体 / {{ allLinks.length }} 条关联 ·
            当前显示 {{ displayNodes.length }} 个实体（默认只展示关联最多的核心实体，避免画面拥挤）
          </p>
        </div>
        <div class="graph-actions">
          <button class="btn btn-sm" type="button" @click="relayout">重新布局</button>
          <button class="btn btn-sm" type="button" :disabled="loading" @click="load">
            {{ loading ? '加载中…' : '刷新' }}
          </button>
        </div>
      </div>

      <!-- 工具栏：搜索实体 + 按关系筛选 + 显示范围 -->
      <div class="graph-toolbar">
        <input
          v-model="keyword"
          class="filter-input"
          type="text"
          placeholder="搜索实体（如：面料、售后、FY2026-001）"
        />
        <select v-model="relationFilter" class="filter-input filter-select">
          <option value="">全部关系类型</option>
          <option v-for="rel in relationOptions" :key="rel" :value="rel">{{ rel }}</option>
        </select>
        <button
          class="btn btn-sm"
          :class="{ 'btn-primary': !showAll }"
          type="button"
          @click="toggleScope"
        >
          {{ showAll ? '只看核心节点' : `显示全部（${allNodes.length}）` }}
        </button>
        <button v-if="keyword || relationFilter" class="btn btn-sm" type="button" @click="resetFilter">
          清空筛选
        </button>
      </div>

      <!-- 实体类型图例：点一下即可隐藏/显示该类实体，画面更清爽 -->
      <div class="graph-type-bar">
        <span class="graph-type-hint">实体类型：</span>
        <button
          v-for="item in typeStats"
          :key="item.type"
          class="graph-type-chip"
          :class="{ off: hiddenTypes[item.type] }"
          type="button"
          @click="toggleType(item.type)"
        >
          <i :style="{ background: colorOfType(item.type) }"></i>
          {{ item.type }} {{ item.count }}
        </button>
      </div>

      <div v-if="errorMsg" class="file-error">{{ errorMsg }}</div>
      <div v-if="!allNodes.length && !loading" class="empty-list">
        暂无图谱数据，请先上传知识文件并等待 Agent2 抽取完成
      </div>

      <div v-else class="graph-layout">
        <div class="graph-canvas" ref="canvasRef">
          <svg :width="width" :height="height" class="graph-svg">
            <defs>
              <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#c9c2b6" />
              </marker>
              <marker id="graph-arrow-active" viewBox="0 0 10 10" refX="9" refY="5"
                      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#a47148" />
              </marker>
            </defs>

            <g v-for="link in visibleLinks" :key="'l-' + link.id">
              <!-- 透明加粗线：扩大点击热区，方便选中连线 -->
              <line
                :x1="posOf(link.source).x"
                :y1="posOf(link.source).y"
                :x2="posOf(link.target).x"
                :y2="posOf(link.target).y"
                stroke="transparent"
                stroke-width="10"
                class="graph-link-hit"
                @click.stop="selectLink(link)"
              />
              <line
                :x1="posOf(link.source).x"
                :y1="posOf(link.source).y"
                :x2="posOf(link.target).x"
                :y2="posOf(link.target).y"
                :stroke="linkStroke(link)"
                :stroke-width="isLinkActive(link) ? 2.4 : 1"
                :marker-end="isLinkActive(link) ? 'url(#graph-arrow-active)' : 'url(#graph-arrow)'"
              />
              <text
                v-if="showLinkLabel(link)"
                :x="(posOf(link.source).x + posOf(link.target).x) / 2"
                :y="(posOf(link.source).y + posOf(link.target).y) / 2 - 4"
                class="graph-link-label"
                text-anchor="middle"
              >{{ link.relation }}</text>
            </g>

            <g
              v-for="node in displayNodes"
              :key="node.id"
              class="graph-node"
              :class="{
                dragging: dragId === node.id,
                highlight: hoverId === node.id,
                selected: selectedId === node.id,
                dim: isDimmed(node),
                hit: matchedIds.includes(node.id)
              }"
              :transform="`translate(${node.x}, ${node.y})`"
              @pointerdown.prevent="startDrag(node, $event)"
              @pointerenter="hoverId = node.id"
              @pointerleave="hoverId = ''"
            >
              <circle :r="radiusOf(node)" :fill="colorOf(node)" stroke="#fff" stroke-width="2" />
              <text class="graph-node-label" text-anchor="middle" :y="radiusOf(node) + 13">
                {{ shortName(node.name) }}
              </text>
            </g>
          </svg>
          <div class="graph-legend">
            <span>拖动节点排版</span>
            <span>单击节点看详情</span>
            <span>单击连线可选中并删除</span>
          </div>
          <div v-if="!displayNodes.length" class="graph-empty">
            当前筛选下没有可显示的实体，请放开实体类型或清空搜索
          </div>
        </div>

        <!-- 右侧面板：节点详情 / 连线详情 / 手动建立关联 -->
        <aside class="graph-detail">
          <template v-if="selectedLink">
            <h3 class="graph-detail-title">关联详情</h3>
            <p class="graph-detail-meta">
              {{ nodeName(selectedLink.source) }}
              <span class="rel-name">{{ selectedLink.relation }}</span>
              {{ nodeName(selectedLink.target) }}
            </p>
            <p class="graph-detail-meta">
              来源：{{ selectedLink.manual ? '管理员手动维护' : (selectedLink.file_name || '文档抽取') }}
            </p>
            <button class="btn btn-danger btn-sm" type="button" :disabled="saving" @click="removeLink(selectedLink)">
              删除这条关联
            </button>
          </template>

          <template v-else-if="selectedNode">
            <h3 class="graph-detail-title">{{ selectedNode.name }}</h3>
            <p class="graph-detail-meta">
              实体类型：{{ selectedNode.type || '实体' }}<br />
              关联关系：{{ selectedRelations.length }} 条（单击下方关系可选中删除）
            </p>
            <ul class="graph-detail-list">
              <li
                v-for="rel in selectedRelations"
                :key="rel.id"
                class="graph-rel-row"
                @click="selectLink(rel.link)"
              >
                <span :class="rel.direction === 'out' ? 'rel-out' : 'rel-in'">
                  {{ rel.direction === 'out' ? '→' : '←' }}
                </span>
                <span class="rel-name">{{ rel.relation }}</span>
                <span class="rel-target">{{ rel.direction === 'out' ? nodeName(rel.link.target) : nodeName(rel.link.source) }}</span>
                <span v-if="rel.link.manual" class="rel-file">手动维护</span>
                <span v-else-if="rel.link.file_name" class="rel-file">{{ rel.link.file_name }}</span>
              </li>
            </ul>
            <button class="btn btn-sm" type="button" @click="selectedId = ''">取消选中</button>
          </template>

          <div v-else class="graph-detail-empty">
            <p>点击任意节点<br />查看实体类型与关联关系</p>
            <p class="graph-detail-tip">提示：搜索框可快速定位实体；点击上方实体类型可隐藏该类节点，画面更清爽。</p>
          </div>

          <!-- 手动建立关联：两个实体都从下拉框里选，关系类型限定预设值 -->
          <div class="graph-link-form">
            <h4 class="graph-form-title">手动建立关联</h4>
            <label class="graph-form-label">起点实体</label>
            <select v-model="formSourceId" class="filter-input filter-select graph-form-select">
              <option value="">请选择起点</option>
              <option v-for="node in nodeOptions" :key="'s-' + node.id" :value="node.id">
                {{ node.name }}（{{ node.type }}）
              </option>
            </select>
            <label class="graph-form-label">关系类型</label>
            <select v-model="formRelation" class="filter-input filter-select graph-form-select">
              <option value="">请选择关系</option>
              <option v-for="rel in relationOptions" :key="'r-' + rel" :value="rel">{{ rel }}</option>
            </select>
            <label class="graph-form-label">终点实体</label>
            <select v-model="formTargetId" class="filter-input filter-select graph-form-select">
              <option value="">请选择终点</option>
              <option v-for="node in nodeOptions" :key="'t-' + node.id" :value="node.id">
                {{ node.name }}（{{ node.type }}）
              </option>
            </select>
            <button
              class="btn btn-primary btn-sm graph-form-submit"
              type="button"
              :disabled="saving"
              @click="createLink"
            >
              {{ saving ? '保存中…' : '建立关联' }}
            </button>
          </div>
        </aside>
      </div>
    </div>

    <Toast :message="toast" :type="toastType" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { request } from '../shared/api'
import Toast from '../components/Toast.vue'

const props = defineProps({
  token: { type: String, default: '' }
})

const canvasRef = ref(null)
const allNodes = ref([])
const allLinks = ref([])
const apiRelationTypes = ref([])
const apiEntityTypes = ref([])
const loading = ref(false)
const saving = ref(false)
const errorMsg = ref('')
const width = ref(640)
const height = ref(460)
const dragId = ref('')
const hoverId = ref('')
const selectedId = ref('')
const selectedLinkId = ref('')
const keyword = ref('')
const relationFilter = ref('')
const showAll = ref(false)
const hiddenTypes = reactive({})
const toast = ref('')
const toastType = ref('info')

const formSourceId = ref('')
const formTargetId = ref('')
const formRelation = ref('')

const CORE_NODE_LIMIT = 36

// 实体类型配色：低饱和大地色，同一类型颜色固定，便于快速辨认
const TYPE_COLORS = {
  商品: '#a47148',
  面料: '#7f8f6d',
  颜色: '#b58b64',
  尺码: '#6f8391',
  检测报告: '#8b7fa0',
  售后政策: '#b0755f',
  保养方式: '#7f9a8d',
  实体: '#9b968c'
}

let dragOffset = { x: 0, y: 0 }
let dragMoved = false

function showToast(message, type = 'info') {
  toast.value = message
  toastType.value = type
  setTimeout(() => { toast.value = '' }, 3000)
}

function colorOfType(type) {
  return TYPE_COLORS[type] || '#9b968c'
}

/** 每个实体的关联数量：用于核心视图排序和节点大小 */
const degreeMap = computed(() => {
  const map = {}
  allLinks.value.forEach((link) => {
    map[link.source] = (map[link.source] || 0) + 1
    map[link.target] = (map[link.target] || 0) + 1
  })
  return map
})

/** 类型统计（图例 + 隐藏开关） */
const typeStats = computed(() => {
  const map = {}
  allNodes.value.forEach((node) => {
    const type = node.type || '实体'
    map[type] = (map[type] || 0) + 1
  })
  return Object.keys(map)
    .map((type) => ({ type, count: map[type] }))
    .sort((a, b) => b.count - a.count)
})

/**
 * 画布展示的节点：
 * 1. 先排除被图例关闭的类型
 * 2. 非「显示全部」时，只保留关联最多的前 N 个，并始终包含当前选中节点
 */
const displayNodes = computed(() => {
  let list = allNodes.value.filter((node) => !hiddenTypes[node.type || '实体'])
  if (!showAll.value && list.length > CORE_NODE_LIMIT) {
    const sorted = [...list].sort((a, b) => (degreeMap.value[b.id] || 0) - (degreeMap.value[a.id] || 0))
    list = sorted.slice(0, CORE_NODE_LIMIT)
    const selected = allNodes.value.find((node) => node.id === selectedId.value)
    if (selected && !list.some((node) => node.id === selected.id) && !hiddenTypes[selected.type || '实体']) {
      list = list.concat(selected)
    }
  }
  return list
})

const displayIds = computed(() => new Set(displayNodes.value.map((node) => node.id)))

/** 当前画布上的连线：两端都在画布上，且符合关系筛选 */
const visibleLinks = computed(() => {
  return allLinks.value.filter((link) => {
    if (!displayIds.value.has(link.source) || !displayIds.value.has(link.target)) return false
    if (relationFilter.value && link.relation !== relationFilter.value) return false
    return true
  })
})

const relationOptions = computed(() => {
  if (apiRelationTypes.value.length) return apiRelationTypes.value
  const set = new Set()
  allLinks.value.forEach((link) => { if (link.relation) set.add(link.relation) })
  return Array.from(set).sort()
})

const nodeOptions = computed(() => {
  return [...allNodes.value].sort((a, b) => String(a.name).localeCompare(String(b.name), 'zh'))
})

const matchedIds = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return []
  return displayNodes.value
    .filter((node) => String(node.name || '').toLowerCase().includes(text))
    .map((node) => node.id)
})

const searchActive = computed(() => Boolean(keyword.value.trim()))

const selectedNode = computed(() => allNodes.value.find((node) => node.id === selectedId.value) || null)
const selectedLink = computed(() => allLinks.value.find((link) => link.id === selectedLinkId.value) || null)

/** 选中节点时可点选的关系列表 */
const selectedRelations = computed(() => {
  if (!selectedId.value) return []
  const result = []
  allLinks.value.forEach((link) => {
    if (link.source === selectedId.value) {
      result.push({ id: link.id, direction: 'out', relation: link.relation, link })
    } else if (link.target === selectedId.value) {
      result.push({ id: link.id, direction: 'in', relation: link.relation, link })
    }
  })
  return result
})

function posOf(id) {
  const node = displayNodes.value.find((item) => item.id === id)
  return node || { x: 0, y: 0 }
}

function nodeName(id) {
  const node = allNodes.value.find((item) => item.id === id)
  return node ? node.name : id
}

function resetFilter() {
  keyword.value = ''
  relationFilter.value = ''
}

function toggleScope() {
  showAll.value = !showAll.value
  layout()
}

function toggleType(type) {
  hiddenTypes[type] = !hiddenTypes[type]
  if (hiddenTypes[type] && selectedNode.value && (selectedNode.value.type || '实体') === type) {
    selectedId.value = ''
  }
  layout()
}

function radiusOf(node) {
  return 9 + Math.min(7, (degreeMap.value[node.id] || 0) / 2)
}

function colorOf(node) {
  return colorOfType(node.type || '实体')
}

function shortName(name) {
  const text = String(name || '')
  return text.length > 8 ? `${text.slice(0, 8)}…` : text
}

function isLinkActive(link) {
  if (selectedLinkId.value === link.id) return true
  return Boolean(selectedId.value) && (link.source === selectedId.value || link.target === selectedId.value)
}

function linkStroke(link) {
  if (selectedLinkId.value === link.id) return '#b0503c'
  if (isLinkActive(link)) return '#a47148'
  return '#d8d3c9'
}

/** 连线标签过多会显得乱：只在选中节点、选中连线或按关系筛选时显示 */
function showLinkLabel(link) {
  return isLinkActive(link) || Boolean(relationFilter.value)
}

function isDimmed(node) {
  if (searchActive.value) return !matchedIds.value.includes(node.id)
  if (!relationFilter.value) return false
  return !visibleLinks.value.some((link) => link.source === node.id || link.target === node.id)
}

/** 画布左侧是否还有空间放宽节点；核心视图下限制更少 */
function layout() {
  const list = displayNodes.value
  if (!list.length) return
  const cx = width.value / 2
  const cy = height.value / 2

  // 1) 初始位置：按实体类型分区域摆放，避免不同类型混在一起
  const groupMap = {}
  list.forEach((node) => {
    const type = node.type || '实体'
    if (!groupMap[type]) groupMap[type] = []
    groupMap[type].push(node)
  })
  const groupKeys = Object.keys(groupMap)
  const baseRadius = Math.min(width.value, height.value) * 0.30
  groupKeys.forEach((type, groupIndex) => {
    const baseAngle = (Math.PI * 2 * groupIndex) / Math.max(1, groupKeys.length)
    const group = groupMap[type]
    group.forEach((node, index) => {
      const spread = Math.PI * 0.75
      const angle = baseAngle + (group.length > 1 ? (index / (group.length - 1) - 0.5) * spread : 0)
      const radius = baseRadius * (0.65 + ((index * 37) % 10) / 33)
      node.x = cx + Math.cos(angle) * radius
      node.y = cy + Math.sin(angle) * radius
    })
  })

  // 2) 力导向迭代：节点互斥、连线拉近、向中心轻微收拢
  const area = width.value * height.value
  const k = Math.sqrt(area / Math.max(1, list.length)) * 0.62
  const ideal = k * 0.95
  const linkList = allLinks.value.filter(
    (link) => list.some((n) => n.id === link.source) && list.some((n) => n.id === link.target)
  )

  for (let iter = 0; iter < 150; iter += 1) {
    const disp = new Map(list.map((node) => [node.id, { x: 0, y: 0 }]))

    // 斥力
    for (let i = 0; i < list.length; i += 1) {
      const a = list[i]
      for (let j = i + 1; j < list.length; j += 1) {
        const b = list[j]
        let dx = a.x - b.x
        let dy = a.y - b.y
        let dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 1) {
          dx = (i % 2 ? 1 : -1) * 1.5
          dy = (j % 2 ? 1 : -1) * 1.5
          dist = 2
        }
        const force = (k * k) / dist
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        const da = disp.get(a.id)
        const db = disp.get(b.id)
        da.x += fx; da.y += fy
        db.x -= fx; db.y -= fy
      }
    }

    // 引力（沿连线）
    linkList.forEach((link) => {
      const a = list.find((node) => node.id === link.source)
      const b = list.find((node) => node.id === link.target)
      if (!a || !b) return
      const dx = a.x - b.x
      const dy = a.y - b.y
      const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy))
      const force = (dist * dist) / k
      const fx = (dx / dist) * force * 0.12
      const fy = (dy / dist) * force * 0.12
      const da = disp.get(a.id)
      const db = disp.get(b.id)
      da.x -= fx; da.y -= fy
      db.x += fx; db.y += fy
    })

    // 重力 + 位置更新（逐步降温，避免节点来回震荡）
    const cooling = 1 - iter / 150
    list.forEach((node) => {
      const d = disp.get(node.id)
      d.x += (cx - node.x) * 0.012
      d.y += (cy - node.y) * 0.012
      const len = Math.sqrt(d.x * d.x + d.y * d.y)
      const maxStep = 18 * cooling + 2
      const step = len > maxStep ? maxStep / len : 1
      node.x += d.x * step
      node.y += d.y * step
      node.x = Math.max(28, Math.min(width.value - 28, node.x))
      node.y = Math.max(28, Math.min(height.value - 28, node.y))
    })
  }
}

function relayout() {
  layout()
  showToast('已重新布局')
}

function resize() {
  const el = canvasRef.value
  if (!el) return
  width.value = Math.max(320, el.clientWidth)
  height.value = Math.max(360, Math.min(560, Math.round(el.clientWidth * 0.78)))
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await request('/kb/graph?limit=1000', { token: props.token })
    allNodes.value = (data.nodes || []).map((node) => ({
      ...node,
      type: node.type || '实体',
      x: 0,
      y: 0
    }))
    allLinks.value = data.links || []
    apiRelationTypes.value = data.relation_types || []
    apiEntityTypes.value = data.entity_types || []
    selectedId.value = ''
    selectedLinkId.value = ''
    resize()
    layout()
  } catch (err) {
    errorMsg.value = err.message || '图谱加载失败'
    allNodes.value = []
    allLinks.value = []
  } finally {
    loading.value = false
  }
}

/** ---------- 节点拖动与单击选中（pointer 事件，同时兼容鼠标和触屏） ---------- */
function startDrag(node, event) {
  dragId.value = node.id
  dragMoved = false
  const rect = canvasRef.value ? canvasRef.value.getBoundingClientRect() : { left: 0, top: 0 }
  dragOffset = {
    x: event.clientX - rect.left - node.x,
    y: event.clientY - rect.top - node.y
  }
  window.addEventListener('pointermove', onDrag)
  window.addEventListener('pointerup', endDrag)
}

function onDrag(event) {
  if (!dragId.value) return
  const el = canvasRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const node = allNodes.value.find((item) => item.id === dragId.value)
  if (!node) return
  const x = event.clientX - rect.left - dragOffset.x
  const y = event.clientY - rect.top - dragOffset.y
  if (!dragMoved && (Math.abs(x - node.x) > 2 || Math.abs(y - node.y) > 2)) {
    dragMoved = true
  }
  node.x = Math.max(20, Math.min(width.value - 20, x))
  node.y = Math.max(20, Math.min(height.value - 20, y))
}

function endDrag() {
  if (dragId.value && !dragMoved) {
    selectedId.value = dragId.value
    selectedLinkId.value = ''
  }
  dragId.value = ''
  window.removeEventListener('pointermove', onDrag)
  window.removeEventListener('pointerup', endDrag)
}

function selectLink(link) {
  selectedLinkId.value = link.id
  selectedId.value = ''
}

/** 选中节点后，手动关联表单的起点自动带出当前实体 */
watch(selectedId, (id) => {
  if (id) formSourceId.value = id
})

/** ---------- 手动新增 / 删除关联 ---------- */
async function createLink() {
  if (saving.value) return
  if (!formSourceId.value || !formTargetId.value) {
    showToast('请选择起点和终点实体', 'error')
    return
  }
  if (formSourceId.value === formTargetId.value) {
    showToast('起点和终点不能是同一个实体', 'error')
    return
  }
  if (!formRelation.value) {
    showToast('请选择关系类型', 'error')
    return
  }
  saving.value = true
  try {
    await request('/kb/graph/relationships', {
      method: 'POST',
      token: ***,
      body: {
        source_id: formSourceId.value,
        target_id: formTargetId.value,
        relation: formRelation.value,
        source_name: nodeName(formSourceId.value),
        target_name: nodeName(formTargetId.value)
      }
    })
    showToast('关联已建立', 'info')
    formRelation.value = ''
    await load()
  } catch (err) {
    showToast(err.message || '关联创建失败', 'error')
  } finally {
    saving.value = false
  }
}

async function removeLink(link) {
  if (saving.value || !link) return
  if (!window.confirm(`确认删除关联「${nodeName(link.source)} ${link.relation} ${nodeName(link.target)}」？`)) {
    return
  }
  saving.value = true
  try {
    await request(`/kb/graph/relationships/${encodeURIComponent(link.id)}`, {
      method: 'DELETE',
      token: ***
    })
    showToast('关联已删除', 'info')
    selectedLinkId.value = ''
    await load()
  } catch (err) {
    showToast(err.message || '关联删除失败', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  window.removeEventListener('pointermove', onDrag)
  window.removeEventListener('pointerup', endDrag)
})
</script>
