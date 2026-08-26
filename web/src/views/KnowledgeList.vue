<template>
  <div>
    <el-card>
      <div style="display:flex;gap:10px;margin-bottom:12px;align-items:center">
        <el-input v-model="keyword" placeholder="搜索标题/内容" style="width:240px" clearable @keyup.enter="load" />
        <el-select v-model="status" placeholder="状态" style="width:120px" clearable @change="load">
          <el-option label="启用" :value="1" /><el-option label="下架" :value="0" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
        <span style="flex:1"></span>
        <el-button v-permission="'kb:unit:edit'" @click="$router.push('/import')">前往导入</el-button>
      </div>

      <el-table :data="rows" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="title" label="标题" min-width="200">
          <template #default="{row}"><el-link @click="openDetail(row)">{{ row.title }}</el-link></template>
        </el-table-column>
        <el-table-column prop="category" label="分类" width="110" />
        <el-table-column prop="file_type" label="格式" width="80" />
        <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{row}">
            <el-tag :type="row.status===1?'success':'info'">{{ row.status===1?'启用':'下架' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" v-permission="'kb:unit:edit'">
          <template #default="{row}">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="确认删除该知识单元？" @confirm="remove(row)">
              <template #reference><el-button link type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination style="margin-top:12px" layout="total, prev, pager, next"
        :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="load" />
    </el-card>

    <!-- 详情 -->
    <el-drawer v-model="detailVisible" :title="detail?.title" size="50%">
      <p><b>分类：</b>{{ detail?.category }} ｜ <b>来源：</b>{{ detail?.source_file_name }} ｜ <b>切片数：</b>{{ detail?.chunk_count }}</p>
      <pre style="white-space:pre-wrap;background:#f7f8fa;padding:12px;border-radius:6px">{{ detail?.content }}</pre>
    </el-drawer>

    <!-- 编辑 -->
    <el-dialog v-model="editVisible" title="编辑知识单元" width="640px">
      <el-form label-width="70px">
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="editForm.category" /></el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="editForm.status" :active-value="1" :inactive-value="0"
                     active-text="启用" inactive-text="下架" />
        </el-form-item>
        <el-form-item label="正文">
          <el-input v-model="editForm.content" type="textarea" :rows="10" />
          <span class="hint">修改正文会自动重新切片并向量索引</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存并重建索引</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { listUnits, getUnit, updateUnit, deleteUnit } from '../api'

const rows = ref([]); const total = ref(0); const page = ref(1); const pageSize = 20
const keyword = ref(''); const status = ref(null); const loading = ref(false)
const detail = ref(null); const detailVisible = ref(false)
const editVisible = ref(false); const saving = ref(false)
const editForm = reactive({ id: null, title: '', category: '', status: 1, content: '' })

async function load() {
  loading.value = true
  try {
    const data = await listUnits({ keyword: keyword.value, status: status.value ?? undefined,
                                   page: page.value, page_size: pageSize })
    rows.value = data.items; total.value = data.total
  } finally { loading.value = false }
}

async function openDetail(row) {
  detail.value = await getUnit(row.id)
  detailVisible.value = true
}

function openEdit(row) {
  getUnit(row.id).then((u) => {
    Object.assign(editForm, { id: u.id, title: u.title, category: u.category,
                              status: u.status, content: u.content })
    editVisible.value = true
  })
}

async function save() {
  saving.value = true
  try {
    await updateUnit(editForm.id, { title: editForm.title, category: editForm.category,
                                    status: editForm.status, content: editForm.content })
    ElMessage.success('已保存并重建索引')
    editVisible.value = false
    load()
  } finally { saving.value = false }
}

async function remove(row) {
  await deleteUnit(row.id)
  ElMessage.success('已删除（含向量索引）')
  load()
}

onMounted(load)
</script>

<style scoped>
.hint { color:#909399; font-size:12px; }
</style>
