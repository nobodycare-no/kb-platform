<template>
  <el-tabs v-model="tab">
    <el-tab-pane label="FAQ 推荐（待审核）" name="recommend">
      <el-table :data="recommends" border stripe size="small">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="question" label="问题" min-width="240" />
        <el-table-column prop="hit_count" label="频次" width="80" />
        <el-table-column prop="answer" label="建议答案" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="170" v-permission="'settle:review'">
          <template #default="{row}">
            <el-button link type="primary" @click="approve(row)">通过并发布</el-button>
            <el-button link type="danger" @click="reject(row)">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <el-tab-pane label="已发布 FAQ 库" name="published">
      <el-table :data="published" border stripe size="small">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="question" label="问题" min-width="240" />
        <el-table-column prop="answer" label="标准答案" min-width="320" show-overflow-tooltip />
        <el-table-column prop="hit_count" label="命中次数" width="100" />
      </el-table>
    </el-tab-pane>

    <el-tab-pane label="知识缺口" name="gaps">
      <el-table :data="gaps" border stripe size="small">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="question_pattern" label="代表问题" min-width="240" />
        <el-table-column prop="ask_count" label="提问频次" width="100" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{row}">
            <el-tag :type="row.status==='resolved'?'success':'warning'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { faqRecommendations, reviewFaq, publishedFaqs, knowledgeGaps } from '../api'

const tab = ref('recommend')
const recommends = ref([]); const published = ref([]); const gaps = ref([])

async function load() {
  recommends.value = await faqRecommendations() || []
  published.value = await publishedFaqs() || []
  gaps.value = await knowledgeGaps() || []
}

async function approve(row) {
  await reviewFaq(row.id, 'approve', row.answer)
  ElMessage.success('已发布并写入缓存')
  load()
}

async function reject(row) {
  await reviewFaq(row.id, 'reject')
  ElMessage.info('已驳回')
  load()
}

onMounted(load)
</script>
