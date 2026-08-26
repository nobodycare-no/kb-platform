<template>
  <el-card>
    <el-upload drag multiple :auto-upload="false" :on-change="onFileChange" :show-file-list="true"
               accept=".txt,.md,.pdf,.docx" v-permission="'kb:unit:edit'">
      <el-icon size="46" style="color:#409EFF"><UploadFilled /></el-icon>
      <div>拖拽文件到此处，或点击选择（PDF / Markdown / Word / TXT，单个 ≤20MB）</div>
    </el-upload>

    <div style="margin-top:14px;display:flex;gap:10px">
      <el-button type="primary" :disabled="!fileList.length || uploading" :loading="uploading"
                 @click="submit">开始导入（{{ fileList.length }} 个文件）</el-button>
      <el-button @click="reset">清空</el-button>
    </div>

    <el-divider />

    <h4 style="margin:4px 0 10px">任务进度</h4>
    <el-table :data="tasks" border size="small">
      <el-table-column prop="task_id" label="#" width="64" />
      <el-table-column prop="file_name" label="文件" min-width="200" />
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{row}">
          <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="error_message" label="失败原因" min-width="220" />
    </el-table>
  </el-card>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importFiles, importTaskStatus } from '../api'

const fileList = ref([])
const tasks = ref([])
const uploading = ref(false)
let timer = null

function onFileChange(file, list) { fileList.value = list }

function reset() { fileList.value = []; tasks.value = [] }

function statusType(s) {
  return { done: 'success', failed: 'danger', embedding: 'warning', parsing: 'warning' }[s] || 'info'
}
function statusText(s) {
  return { pending: '排队中', parsing: '解析中', embedding: '向量化中', done: '完成', failed: '失败' }[s] || s
}

async function submit() {
  const bad = fileList.value.find(f => f.size > 20 * 1024 * 1024)
  if (bad) return ElMessage.error(`文件过大: ${bad.name}`)
  uploading.value = true
  try {
    const fd = new FormData()
    for (const f of fileList.value) fd.append('files', f.raw, f.name)
    const data = await importFiles(fd)
    tasks.value = data.tasks
    ElMessage.success(`已提交 ${data.tasks.length} 个导入任务`)
    poll(data.batch_no, data.tasks.map(t => t.task_id))
  } finally { uploading.value = false }
}

function poll(batchNo, ids) {
  clearInterval(timer)
  timer = setInterval(async () => {
    const data = await importTaskStatus(ids)
    tasks.value = data.map(t => ({ ...t }))
    if (data.every(t => t.status === 'done' || t.status === 'failed')) clearInterval(timer)
  }, 800)
}
</script>
