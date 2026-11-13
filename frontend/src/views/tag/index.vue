<template>
  <section class="page" data-module="tag">
    <header class="page-head">
      <div>
        <h2>采集数据标注管理</h2>
        <p class="page-desc">维护采集数据的标注类型、标签管理与复核记录，为采集数据标注提供可追溯的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记标注记录</button>
        <button class="btn" type="button" @click="goReview">复核批次</button>
        <button class="btn" type="button" @click="exportRows">导出采集数据标注清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="filters[field.key]" :placeholder="`按${field.label}检索`" />
      </label>
      <label class="filter-item">
        <span>复核状态</span>
        <select v-model="filters.review_status">
          <option value="">全部</option>
          <option v-for="item in reviewStatuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>记录状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集数据标注数据，可先登记标注记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集数据标注记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { readError, request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/tag'
const columns = ["标注编号", "数据记录", "标注类型", "标注标签", "标注批次", "复核状态", "标注人", "标注时间"]
const actions = ["提交复核", "归档标注", "删除标注"]
const statuses = ["草稿", "已标注", "已复核", "已归档"]
const reviewStatuses = ["待裁定", "已裁定", "已退回"]
const stats = [{"label": "标注记录总数", "value": 0}, {"label": "已复核标注", "value": 0}, {"label": "已归档标注", "value": 0}]

// 筛选条件：编号、类型、标签、批次、复核状态、记录状态同时给出时后端取交集
const filterFields = [
  { key: 'keyword', label: '标注编号' },
  { key: 'tag_type', label: '标注类型' },
  { key: 'tag_label', label: '标注标签' },
  { key: 'tag_batch', label: '标注批次' },
]

const router = useRouter()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '标注记录登记入口尚未接入审批流'
}

function goReview() {
  void router.push('/tag/review')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '采集数据标注动作未生效，请稍后重试'))
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集数据标注操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    const trimmed = String(value ?? '').trim()
    if (trimmed) query.set(key, trimmed)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error(await readError(response, '标注记录列表读取失败'))
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集数据标注列表读取失败'
  }
}

onMounted(reload)
</script>
