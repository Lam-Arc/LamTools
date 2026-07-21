import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'

const router = createRouter({
  history: window.location.protocol === 'file:' ? createWebHashHistory() : createWebHistory(),
  routes: [
    { path: '/', name: 'workbench', component: () => import('@/views/WorkbenchView.vue') },
  ],
})

export default router
