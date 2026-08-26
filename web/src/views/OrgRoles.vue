<template>
  <el-card>
    <div style="display:flex;gap:10px;margin-bottom:12px">
      <span style="flex:1"></span>
      <el-button v-permission="'org:role:edit'" type="primary" @click="openCreate">新增角色</el-button>
    </div>

    <el-table :data="roles" border stripe>
      <el-table-column prop="id" label="ID" width="64" />
      <el-table-column prop="role_name" label="角色名" width="160" />
      <el-table-column prop="role_code" label="编码" width="140" />
      <el-table-column prop="description" label="说明" min-width="180" />
      <el-table-column label="权限码" min-width="260">
        <template #default="{row}">
          <el-tag v-for="c in row.permission_codes" :key="c" size="small" style="margin-right:4px">{{ c }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" v-permission="'org:role:edit'">
        <template #default="{row}">
          <el-button link type="primary" @click="openPerms(row)">分配权限</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" title="新增角色" width="420px">
      <el-form label-width="80px">
        <el-form-item label="角色名"><el-input v-model="createForm.role_name" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="createForm.role_code" placeholder="如 fin_admin" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="createForm.description" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible=false">取消</el-button>
        <el-button type="primary" @click="saveCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="permVisible" :title="`分配权限 — ${current?.role_name}`" width="520px">
      <el-checkbox-group v-model="selectedCodes">
        <el-checkbox v-for="c in ALL_PERMS" :key="c.code" :value="c.code">{{ c.label }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="permVisible=false">取消</el-button>
        <el-button type="primary" @click="savePerms">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listRoles, createRole, updateRolePerms } from '../api'

const ALL_PERMS = [
  { code: 'ai:chat', label: 'AI 问答' },
  { code: 'kb:unit:edit', label: '知识维护' },
  { code: 'kb:import', label: '知识导入' },
  { code: 'dash:view', label: '看板查看' },
  { code: 'settle:review', label: '沉淀审核' },
  { code: 'org:user:view', label: '用户查看' },
  { code: 'org:user:edit', label: '用户编辑' },
  { code: 'org:dept:edit', label: '部门编辑' },
  { code: 'org:role:edit', label: '角色编辑' }
]

const roles = ref([])
const createVisible = ref(false)
const permVisible = ref(false)
const current = ref(null)
const selectedCodes = ref([])
const createForm = reactive({ role_name: '', role_code: '', description: '' })

async function load() { roles.value = await listRoles() || [] }

function openCreate() {
  Object.assign(createForm, { role_name: '', role_code: '', description: '' })
  createVisible.value = true
}

async function saveCreate() {
  await createRole(createForm)
  ElMessage.success('已创建')
  createVisible.value = false
  load()
}

function openPerms(row) {
  current.value = row
  selectedCodes.value = [...row.permission_codes]
  permVisible.value = true
}

async function savePerms() {
  await updateRolePerms(current.value.id, selectedCodes.value)
  ElMessage.success('权限已更新（立即生效）')
  permVisible.value = false
  load()
}

onMounted(load)
</script>
