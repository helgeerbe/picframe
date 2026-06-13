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
      path: '/filters',
      name: 'filters',
      component: () => import('../views/FiltersView.vue')
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
