<template>
  <div>
    <el-row :gutter="12">
      <el-col :span="4" v-for="card in cards" :key="card.label">
        <el-card><el-statistic :title="card.label" :value="card.value" /></el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top:12px">
      <el-col :span="12">
        <el-card header="高频问题 TOP10">
          <v-chart :option="questionOption" style="height:320px" autoresize />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card header="知识单元热度 TOP10">
          <v-chart :option="unitOption" style="height:320px" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <el-row style="margin-top:12px">
      <el-col :span="24">
        <el-card header="Token 消耗 / 平均耗时趋势">
          <v-chart :option="trendOption" style="height:300px" autoresize />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { dashMetrics, dashQuestionRank, dashUnitRank, dashTokenStats } from '../api'

use([CanvasRenderer, BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent])

const metrics = ref({})
const qRank = ref([])
const uRank = ref([])
const tokens = ref([])

const cards = computed(() => [
  { label: '访问次数', value: metrics.value.total_visits ?? 0 },
  { label: '独立访客', value: metrics.value.unique_users ?? 0 },
  { label: '知识单元', value: metrics.value.unit_count ?? 0 },
  { label: 'Token 总量', value: metrics.value.total_tokens ?? 0 },
  { label: '平均耗时(ms)', value: Math.round(metrics.value.avg_response_ms ?? 0) }
])

const questionOption = computed(() => ({
  tooltip: {},
  grid: { left: 8, right: 16, bottom: 8, top: 16, containLabel: true },
  xAxis: { type: 'value' },
  yAxis: { type: 'category',
           data: (qRank.value || []).map(i => i.question?.slice(0, 18) ?? ''),
           inverse: true },
  series: [{ type: 'bar', data: (qRank.value || []).map(i => i.cnt),
             itemStyle: { color: '#409EFF' } }]
}))

const unitOption = computed(() => ({
  tooltip: {},
  grid: { left: 8, right: 16, bottom: 8, top: 16, containLabel: true },
  xAxis: { type: 'value' },
  yAxis: { type: 'category', data: (uRank.value || []).map(i => i.title), inverse: true },
  series: [{ type: 'bar', data: (uRank.value || []).map(i => i.cnt),
             itemStyle: { color: '#67C23A' } }]
}))

const trendOption = computed(() => {
  const t = tokens.value || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Token 消耗', '平均耗时(ms)'] },
    xAxis: { type: 'category', data: t.map(i => i.day) },
    yAxis: [{ type: 'value', name: 'Token' }, { type: 'value', name: 'ms' }],
    series: [
      { name: 'Token 消耗', type: 'line', smooth: true,
        data: t.map(i => i.total_tokens), itemStyle: { color: '#409EFF' } },
      { name: '平均耗时(ms)', type: 'line', smooth: true, yAxisIndex: 1,
        data: t.map(i => i.avg_response_ms), itemStyle: { color: '#E6A23C' } }
    ]
  }
})

onMounted(async () => {
  metrics.value = await dashMetrics() || {}
  qRank.value = await dashQuestionRank() || []
  uRank.value = await dashUnitRank() || []
  tokens.value = await dashTokenStats() || []
})
</script>

<style scoped>
.el-col { margin-bottom: 2px; }
</style>
