/** v-permission="'code'" 或 v-permission="['a','b']"：无权限则移除元素 */
import { useAuthStore } from '../stores/auth'

export default {
  mounted(el, binding) {
    const auth = useAuthStore()
    const required = Array.isArray(binding.value) ? binding.value : [binding.value]
    const ok = auth.isSuper || required.some((c) => auth.permissions.includes(c))
    if (!ok) el.parentNode?.removeChild(el)
  }
}
