import { createRouter, createWebHistory } from 'vue-router'
import LibraryView from '@/views/LibraryView.vue'
import ScrapersView from '@/views/ScrapersView.vue'
import SettingsView from '@/views/SettingsView.vue'
import WorkspaceView from '@/views/WorkspaceView.vue'

const routes = [
  { path: '/', redirect: '/library' },
  {
    path: '/library',
    name: 'library',
    component: LibraryView,
    meta: { title: 'Library' },
  },
  {
    path: '/novels/:id',
    name: 'workspace',
    component: WorkspaceView,
    meta: { title: 'Workspace' },
  },
  {
    path: '/scrapers',
    name: 'scrapers',
    component: ScrapersView,
    meta: { title: 'Scrapers' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: SettingsView,
    meta: { title: 'Settings' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/library' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = to.meta?.title ? `${to.meta.title} · Translatale` : 'Translatale'
})

export default router
