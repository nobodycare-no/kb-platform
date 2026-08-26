/** axios 实例：token 注入、401 跳登录、统一错误提示 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('kb_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        ElMessage.error(body.message || '请求失败')
        return Promise.reject(new Error(body.message))
      }
      return body.data
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data
    if (status === 401) {
      localStorage.removeItem('kb_token')
      localStorage.removeItem('kb_user')
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    ElMessage.error(detail?.message || detail?.detail || `请求失败(${status || '网络异常'})`)
    return Promise.reject(error)
  }
)

export default http
