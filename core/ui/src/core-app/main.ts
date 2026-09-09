import { createApp } from 'vue'
import {
  createDirectTransport,
  createLamToolsRuntime,
  LamToolsApp,
} from '../index'

const transport = createDirectTransport({
  apiBase: (window as Window & { __LAMTOOLS_API_BASE__?: string }).__LAMTOOLS_API_BASE__ || '/api/core',
})
const runtime = createLamToolsRuntime({
  transport,
  platform: 'web',
  capabilities: {
    filePicker: true,
    notifications: false,
    desktopWindow: false,
  },
})

createApp(LamToolsApp, { runtime }).mount('#app')
