import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { initLocale } from './i18n'
import { initTheme } from './composables/useTheme'
import './style.css'

// Apply the stored theme and language before the first paint.
initTheme()
initLocale()

createApp(App).use(router).mount('#app')
