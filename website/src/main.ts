import { createApp } from 'vue'
import App from './App.vue'
import sundayIcon from '@ui/assets/sunday-app-icon-dark-display.png'

const favicon = document.querySelector<HTMLLinkElement>('link[rel="icon"]') || document.createElement('link')
favicon.rel = 'icon'
favicon.href = sundayIcon
if (!favicon.parentNode) document.head.appendChild(favicon)

createApp(App).mount('#app')
