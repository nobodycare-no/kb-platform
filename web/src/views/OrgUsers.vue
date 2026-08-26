<template>
  <el-card>
    <div style="display:flex;gap:10px;margin-bottom:12px">
      <el-input v-model="keyword" placeholder="用户名/姓名" style="width:220px" clearable @keyup.enter="load" />
      <el-button type="primary" @click="load">查询</el-button>
      <span style="flex:1"></span>
      <el-button v-permission="'org:user:edit'" type="primary" @click="openCreate">新增用户</el-button>
    </div>

    <el-table :data="rows" border stripe v-loading="loading">
      <el-table-column prop="id" label="ID" width="64" />
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="display_name" label="姓名" width="140" />
      <el-table-column prop="department_id" label="部门ID" width="90" />
      <el-table-column prop="role_ids" label="角色" min-width="160">
        <template #default="{row}">{{ roleName(row.role_ids) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90">
        <template #default="{row}">
          <el-tag :type="row.status===1?'success':'info'">{{ row.status===1?'启用':'停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="is_super" label="超管" width="80">
        <template #default="{row}"><el-tag v-if="row.is_super" type="warning">是</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="170" v-permission="'org:user:edit'">
        <template #default="{row}">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link :type="row.status===1?'danger':'success'" @click="toggleStatus(row)">
            {{ row.status===1?'停用':'启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, prev, pager, next"
      :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="load" />

    <!-- 新增/编辑 -->
    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑用户' : '新增用户'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!form.id" />
        </el-form-item>
        <el-form-item :label="form.id ? '重置密码' : '密码'">
          <el-input v-model="form.password" show-password
                    :placeholder="form.id ? '留空则不修改' : ''" />
        </el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="form.department_id" clearable style="width:100%">
            <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple style="width:100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.role_name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listUsers, createUser, updateUser, listRoles, listDepartments } from '../api'

const rows = ref([]); const total = ref(0); const page = ref(1); const pageSize = 20
const keyword = ref(''); const loading = ref(false)
const depts = ref([]); const roles = ref([])
const dialogVisible = ref(false); const saving = ref(false)
const form = reactive({ id: null, username: '', password: '', display_name: '',
                        department_id: null, role_ids: [] })

function roleName(ids) {
  return ids.map(id => roles.value.find(r => r.id === id)?.role_name || `角色${id}`).join('、') || '—'
}

async function load() {
  loading.value = true
  try {
    const data = await listUsers({ keyword: keyword.value, page: page.value, page_size: pageSize })
    rows.value = data.items; total.value = data.total
  } finally { loading.value = false }
}

function openCreate() {
  Object.assign(form, { id: null, username: '', password: '', display_name: '',
                        department_id: null, role_ids: [] })
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, { id: row.id, username: row.username, password: '',
                        display_name: row.display_name, department_id: row.department_id,
                        role_ids: row.role_ids })
  dialogVisible.value = true
}

async function save() {
  saving.value = true
  try {
    if (form.id) {
      const payload = { display_name: form.display_name, department_id: form.department_id,
                        role_ids: form.role_ids }
      if (form.password) payload.password = form.password
      await updateUser(form.id, payload)
    } else {
      await createUser(form)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    load()
  } finally { saving.value = false }
}

async function toggleStatus(row) {
  await updateUser(row.id, { status: row.status === 1 ? 0 : 1 })
  load()
}

onMounted(async () => {
  load()
  depts.value = await listDepartments() || []
  roles.value = await listRoles() || []
})
</script>
