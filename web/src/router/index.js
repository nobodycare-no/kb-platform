import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    redirect: '/chat',
    children: [
      { path: 'chat', name: 'chat', component: () => import('../views/ChatWorkbench.vue'), meta: { title: 'AI 对话', perm: 'ai:chat' } },
      { path: 'knowledge', name: 'knowledge', component: () => import('../views/KnowledgeList.vue'), meta: { title: '知识单元', perm: 'ai:chat' } },
      { path: 'import', name: 'import', component: () => import('../views/ImportCenter.vue'), meta: { title: '导入中心', perm: 'ai:chat' } },
      { path: 'org/users', name: 'orgUsers', component: () => import('../views/OrgUsers.vue'), meta: { title: '用户管理', perm: 'org:user:view' } },
      { path: 'org/roles', name: 'orgRoles', component: () => import('../views/OrgRoles.vue'), meta: { title: '角色权限', perm: 'org:user:view' } },
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '数据看板' } },
      { path: 'settlement', name: 'settlement', component: () => import('../views/Settlement.vue'), meta: { title: '知识沉淀' } }
    ]
  }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && auth.isLoggedIn) return { path: '/' }
  return true
})

export default router
