<template>
  <el-container style="height:100%">
    <el-aside width="210px" class="aside">
      <div class="logo">📚 知识库平台</div>
      <el-menu :default-active="$route.path" router background-color="#1f2d3d"
               text-color="#bfcbd9" active-text-color="#409EFF">
        <el-menu-item index="/chat"><el-icon><ChatDotRound /></el-icon>AI 对话</el-menu-item>
        <el-menu-item index="/knowledge"><el-icon><Collection /></el-icon>知识单元</el-menu-item>
        <el-menu-item index="/import" v-permission="'kb:unit:edit'"><el-icon><Upload /></el-icon>导入中心</el-menu-item>
        <el-menu-item index="/dashboard"><el-icon><DataLine /></el-icon>数据看板</el-menu-item>
        <el-menu-item index="/settlement"><el-icon><MagicStick /></el-icon>知识沉淀</el-menu-item>
        <el-menu-item index="/org/users" v-permission="'org:user:view'"><el-icon><User /></el-icon>用户管理</el-menu-item>
        <el-menu-item index="/org/roles" v-permission="'org:user:view'"><el-icon><Key /></el-icon>角色权限</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="page-title">{{ $route.meta.title }}</span>
        <el-dropdown @command="onCommand">
          <span class="user-chip">
            <el-icon><Avatar /></el-icon>
            {{ auth.user?.display_name || auth.user?.username }}
            <el-tag v-if="auth.user?.department_id" size="small" type="info" style="margin-left:6px">部门 {{ auth.user.department_id }}</el-tag>
            <el-tag v-if="auth.isSuper" size="small" type="warning" style="margin-left:6px">超管</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                角色：{{ auth.permissions.length ? auth.permissions.join('、') : '（无）' }}
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main style="padding:16px; background:#f5f7fa">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

function onCommand(cmd) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.aside { background: #1f2d3d; }
.logo { color:#fff; height:56px; display:flex; align-items:center; justify-content:center; font-size:17px; letter-spacing:1px; }
.aside :deep(.el-menu) { border-right: none; }
.header { background:#fff; display:flex; align-items:center; justify-content:space-between;
          border-bottom:1px solid #e6e6e6; }
.page-title { font-size:16px; font-weight:600; }
.user-chip { cursor:pointer; display:flex; align-items:center; gap:4px; color:#303133; }
</style>
