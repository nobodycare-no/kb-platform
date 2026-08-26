import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('kb_token') || '',
    user: JSON.parse(localStorage.getItem('kb_user') || 'null'),
    permissions: JSON.parse(localStorage.getItem('kb_perms') || '[]')
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    isSuper: (s) => !!s.user?.is_super
  },
  actions: {
    setLogin(token, user, permissions) {
      this.token = token
      this.user = user
      this.permissions = permissions || []
      localStorage.setItem('kb_token', token)
      localStorage.setItem('kb_user', JSON.stringify(user))
      localStorage.setItem('kb_perms', JSON.stringify(this.permissions))
    },
    setMe(user, permissions) {
      this.user = user
      this.permissions = permissions || []
      localStorage.setItem('kb_user', JSON.stringify(user))
      localStorage.setItem('kb_perms', JSON.stringify(this.permissions))
    },
    logout() {
      this.token = ''
      this.user = null
      this.permissions = []
      localStorage.removeItem('kb_token')
      localStorage.removeItem('kb_user')
      localStorage.removeItem('kb_perms')
    }
  }
})
