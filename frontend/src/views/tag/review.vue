<template>
  <section class="page" data-module="tag-review">
    <header class="page-head">
      <div>
        <h2>标注复核批次</h2>
        <p class="page-desc">
          按批次顺序或最后修改时间排列复核队列；重新打开批次时延续已完成位置，
          工作集只保留仍需裁定或已退回的条目，新登记的记录只追加到队尾。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="goTagList">返回标注列表</button>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="openBatch">
      <label class="filter-item">
        <span>标注批次</span>
        <input v-model="openForm.batch" list="tag-batch-options" placeholder="如 BATCH-2026-09A" required />
        <datalist id="tag-batch-options">
          <option v-for="item in batchOptions" :key="item" :value="item" />
        </datalist>
      </label>
      <label class="filter-item">
        <span>标注标签（可选）</span>
        <input v-model="openForm.label" list="tag-label-options" placeholder="按标签定位，如 地点" />
        <datalist id="tag-label-options">
          <option v-for="item in labelOptions" :key="item" :value="item" />
        </datalist>
      </label>
      <label class="filter-item">
        <span>标注类型（可选）</span>
        <input v-model="openForm.type" placeholder="按类型定位" />
      </label>
      <button class="btn primary" type="submit">打开 / 继续复核批次</button>
    </form>

    <div class="filter-bar sort-bar">
      <span class="sort-label">批次排序：</span>
      <button class="btn" :class="{ primary: sort === 'batch' }" type="button" @click="changeSort('batch')">按批次顺序</button>
      <button class="btn" :class="{ primary: sort === 'time' }" type="button" @click="changeSort('time')">按最后修改时间</button>
      <button class="btn ghost" type="button" @click="toggleOrder">{{ order === 'asc' ? '升序' : '降序' }}</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>批次号</th>
          <th>定位条件</th>
          <th>复核进度</th>
          <th>待裁定</th>
          <th>已退回</th>
          <th>已完成位置</th>
          <th>最后修改时间</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="batch in batches" :key="String(batch.id)" :class="{ 'active-row': currentBatchId === Number(batch.id) }">
          <td>{{ batch.批次号 }}</td>
          <td>{{ scopeText(batch) }}</td>
          <td>{{ batch.已裁定 }}/{{ batch.总数 }}</td>
          <td>{{ batch.待裁定 }}</td>
          <td>{{ batch.已退回 }}</td>
          <td>{{ batch.已完成位置 }}</td>
          <td>{{ batch.最后修改时间 }}</td>
          <td>{{ batch.status }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="enterBatch(Number(batch.id))">继续复核</button>
          </td>
        </tr>
        <tr v-if="!batches.length">
          <td colspan="9" class="empty-state">暂无复核批次，可先在上方按批次与标签打开一个</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 个复核批次</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="gotoPage(page - 1)">上一页</button>
        <button
          v-for="p in pageNumbers"
          :key="p"
          class="btn"
          :class="{ primary: p === page }"
          type="button"
          @click="gotoPage(p)"
        >{{ p }}</button>
        <button class="btn" type="button" :disabled="page >= pageCount" @click="gotoPage(page + 1)">下一页</button>
        <input v-model.number="jumpPage" class="page-jump" type="number" min="1" :max="pageCount" />
        <button class="btn" type="button" @click="gotoPage(jumpPage)">跳转</button>
      </span>
    </footer>

    <section v-if="currentBatch" class="review-panel">
      <h3>
        批次 {{ currentBatch.批次号 }} · 待复核 {{ currentBatch.待复核 }} 条
        <small>已完成位置 {{ currentBatch.已完成位置 }}/{{ currentBatch.总数 }} · 最后修改时间 {{ currentBatch.最后修改时间 }}</small>
      </h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>标注编号</th>
            <th>数据记录</th>
            <th>标注类型</th>
            <th>标注标签</th>
            <th>队列状态</th>
            <th>标注人</th>
            <th>标注时间</th>
            <th>裁定</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in group" :key="row.entry_id">
            <td>{{ row.标注编号 }}</td>
            <td>{{ row.数据记录 }}</td>
            <td>{{ row.标注类型 }}</td>
            <td>{{ row.标注标签 }}</td>
            <td>{{ row.队列状态 }}</td>
            <td>{{ row.标注人 }}</td>
            <td>{{ row.标注时间 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="decide(row, '通过')">裁定通过</button>
              <button class="link" type="button" @click="decide(row, '退回')">退回</button>
            </td>
          </tr>
          <tr v-if="!group.length">
            <td colspan="8" class="empty-state">本批次没有待裁定或已退回的条目，复核已完成</td>
          </tr>
        </tbody>
      </table>
      <div class="panel-foot">
        <button class="btn" type="button" @click="loadGroup">刷新下一组</button>
        <span class="panel-tip">每组 {{ groupSize }} 条，裁定后自动带入下一组未完成条目</span>
      </div>
    </section>

    <footer class="page-foot">
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { readError, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type BatchRow = Record<string, any>
type GroupRow = {
  entry_id: number
  revision: number
  队列状态: string
  标注编号: string
  数据记录: string
  标注类型: string
  标注标签: string
  标注人: string
  标注时间: string
}

const ENDPOINT = '/api/tag'
const GROUP_SIZE = 5

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const batches = ref<BatchRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(5)
const sort = ref<'batch' | 'time'>('batch')
const order = ref<'asc' | 'desc'>('asc')
const jumpPage = ref(1)
const batchOptions = ref<string[]>([])
const labelOptions = ref<string[]>([])
const openForm = ref({ batch: '', label: '', type: '' })

const currentBatchId = ref<number | null>(null)
const currentBatch = ref<BatchRow | null>(null)
const group = ref<GroupRow[]>([])
const groupSize = ref(GROUP_SIZE)
const errorMessage = ref('')
const noticeMessage = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const pageNumbers = computed(() => {
  const pages: number[] = []
  for (let p = 1; p <= pageCount.value; p += 1) pages.push(p)
  return pages
})

function scopeText(batch: BatchRow) {
  const scope = (batch.定位条件 ?? {}) as Record<string, string>
  const parts = Object.entries(scope).map(([key, value]) => `${key}=${value}`)
  return parts.length ? parts.join('，') : '整批'
}

/** 把页码、排序、当前批次写进路由查询：分页后仍定位同一批次，返回时延续当前页。 */
function syncQuery() {
  const query: Record<string, string> = {
    page: String(page.value),
    sort: sort.value,
    order: order.value,
  }
  if (currentBatchId.value) query.batch = String(currentBatchId.value)
  void router.replace({ query })
}

async function loadBatches() {
  const query = new URLSearchParams({
    page: String(page.value),
    size: String(size.value),
    sort: sort.value,
    order: order.value,
  })
  const response = await request(`${ENDPOINT}/review-batches?${query.toString()}`)
  if (!response.ok) throw new Error(await readError(response, '复核批次列表读取失败'))
  const payload = await response.json()
  batches.value = payload.items ?? []
  total.value = payload.total ?? 0
}

async function loadGroup() {
  if (!currentBatchId.value) return
  const response = await request(`${ENDPOINT}/review-batches/${currentBatchId.value}/next?size=${groupSize.value}`)
  if (response.status === 404) {
    // 批次已不存在（如服务重启后内存数据重置）：清掉定位，避免反复报错
    currentBatchId.value = null
    currentBatch.value = null
    group.value = []
    syncQuery()
    return
  }
  if (!response.ok) throw new Error(await readError(response, '复核工作集读取失败'))
  const payload = await response.json()
  group.value = payload.items ?? []
  currentBatch.value = payload.batch ?? null
}

async function refresh() {
  errorMessage.value = ''
  try {
    await loadBatches()
    if (currentBatchId.value) await loadGroup()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核批次数据读取失败'
  }
}

function gotoPage(target: number) {
  const next = Math.min(Math.max(1, Number(target) || 1), pageCount.value)
  if (next === page.value) return
  page.value = next
  jumpPage.value = next
  syncQuery()
  void refresh()
}

function changeSort(next: 'batch' | 'time') {
  if (sort.value === next) return
  sort.value = next
  order.value = next === 'time' ? 'desc' : 'asc'
  page.value = 1
  jumpPage.value = 1
  syncQuery()
  void refresh()
}

function toggleOrder() {
  order.value = order.value === 'asc' ? 'desc' : 'asc'
  syncQuery()
  void refresh()
}

async function openBatch() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/review-batches`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          批次号: openForm.value.batch.trim(),
          标注标签: openForm.value.label.trim() || undefined,
          标注类型: openForm.value.type.trim() || undefined,
          复核人: session.operator,
        },
      }),
    })
    if (!response.ok) throw new Error(await readError(response, '复核批次打开失败'))
    const payload = await response.json()
    noticeMessage.value = payload.message ?? '复核批次已打开'
    const id = Number(payload.entry?.id)
    if (id) {
      currentBatchId.value = id
      syncQuery()
    }
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核批次打开失败'
  }
}

function enterBatch(id: number) {
  currentBatchId.value = id
  syncQuery()
  void refresh()
}

async function decide(row: GroupRow, decision: '通过' | '退回') {
  if (!currentBatchId.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/review-batches/${currentBatchId.value}/entries/${row.entry_id}`,
      {
        method: 'POST',
        body: JSON.stringify({
          values: { 裁定: decision, base_revision: row.revision, 复核人: session.operator },
        }),
      },
    )
    if (response.status === 409) {
      // 后到请求：对方已先完成状态推进，给出明确提示并刷新工作集
      errorMessage.value = await readError(response, '该记录已被他人先行推进，本次提交未生效')
      await refresh()
      return
    }
    if (!response.ok) throw new Error(await readError(response, '复核裁定提交失败'))
    const payload = await response.json()
    noticeMessage.value = payload.message ?? '裁定已提交'
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核裁定提交失败'
  }
}

function goTagList() {
  void router.push('/tag')
}

async function loadOptions() {
  try {
    const response = await request(`${ENDPOINT}/batches`)
    if (!response.ok) return
    const payload = await response.json()
    batchOptions.value = payload.批次 ?? []
    labelOptions.value = payload.标签 ?? []
  } catch {
    /* 下拉选项加载失败不阻塞页面 */
  }
}

onMounted(async () => {
  // 从路由查询恢复页码、排序与当前批次：返回本页时延续上次状态
  const queryPage = Number(route.query.page)
  if (Number.isInteger(queryPage) && queryPage > 0) page.value = queryPage
  if (route.query.sort === 'time' || route.query.sort === 'batch') sort.value = route.query.sort
  if (route.query.order === 'asc' || route.query.order === 'desc') order.value = route.query.order
  const queryBatch = Number(route.query.batch)
  if (Number.isInteger(queryBatch) && queryBatch > 0) currentBatchId.value = queryBatch
  jumpPage.value = page.value
  await Promise.all([refresh(), loadOptions()])
})

watch(page, (value) => {
  jumpPage.value = value
})
</script>
