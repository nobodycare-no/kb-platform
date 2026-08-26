/** 后端 API 封装（对齐 SDD §5 端点清单） */
import http from './http'

export const login = (data) => http.post('/auth/login', data)
export const fetchMe = () => http.get('/auth/me')

// 组织
export const listDepartments = () => http.get('/org/departments')
export const createDepartment = (d) => http.post('/org/departments', d)
export const listUsers = (params) => http.get('/org/users', { params })
export const createUser = (u) => http.post('/org/users', u)
export const updateUser = (id, u) => http.put(`/org/users/${id}`, u)
export const listRoles = () => http.get('/org/roles')
export const createRole = (r) => http.post('/org/roles', r)
export const updateRolePerms = (id, codes) => http.put(`/org/roles/${id}/permissions`, { permission_codes: codes })

// 知识
export const importFiles = (formData, onProgress) =>
  http.post('/knowledge/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress
  })
export const importTaskStatus = (ids) => http.get('/knowledge/import/tasks', { params: { ids: ids.join(',') } })
export const listUnits = (params) => http.get('/knowledge/units', { params })
export const getUnit = (id) => http.get(`/knowledge/units/${id}`)
export const updateUnit = (id, payload) => http.put(`/knowledge/units/${id}`, payload)
export const deleteUnit = (id) => http.delete(`/knowledge/units/${id}`)
export const checkPermissions = (userId, unitIds) =>
  http.post('/knowledge/check-permissions', { user_id: userId, unit_ids: unitIds })

// AI 会话
export const createSession = (title) => http.post('/ai/sessions', title ? { title } : {})
export const listSessions = () => http.get('/ai/sessions')
export const sessionMessages = (id) => http.get(`/ai/sessions/${id}/messages`)

// 看板 & 沉淀
export const dashMetrics = () => http.get('/dashboard/metrics')
export const dashQuestionRank = () => http.get('/dashboard/rankings/questions')
export const dashUnitRank = () => http.get('/dashboard/rankings/units')
export const dashTokenStats = () => http.get('/dashboard/stats/tokens')
export const faqRecommendations = () => http.get('/settlement/faqs/recommendations')
export const reviewFaq = (id, action, editedAnswer) =>
  http.post(`/settlement/faqs/${id}/review`, { action, edited_answer: editedAnswer })
export const publishedFaqs = () => http.get('/settlement/faqs/published')
export const knowledgeGaps = () => http.get('/settlement/knowledge-gaps')
