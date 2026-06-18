import { createRouter, createWebHistory } from 'vue-router'
import RemoteView from '../views/RemoteView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'remote',
      component: RemoteView
    },
    {
      path: '/appearance',
      name: 'appearance',
      component: () => import('../views/AppearanceView.vue')
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue')
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('../views/LogsView.vue')
    }
  ]
})

export default router
