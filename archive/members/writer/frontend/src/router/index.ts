// ============================================================
// Vue Router configuration for LamWriter Console
// ============================================================

import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'

const router = createRouter({
  history: window.location.protocol === 'file:' ? createWebHashHistory() : createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'workbench',
      component: () => import('@/views/CoreWorkbenchView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
    },
  ],
})

export default router
