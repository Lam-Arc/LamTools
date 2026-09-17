import { onMounted, onUnmounted, ref } from 'vue'

export type SiteTheme = 'ivory' | 'graphite'

const STORAGE_KEY = 'sunday.site.theme'

function storedTheme(): SiteTheme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value === 'ivory' || value === 'graphite' ? value : null
  } catch {
    return null
  }
}

function systemTheme(): SiteTheme {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'ivory' : 'graphite'
}

export function useSiteTheme() {
  const saved = storedTheme()
  const followsSystem = ref(!saved)
  const theme = ref<SiteTheme>(saved || systemTheme())
  let query: MediaQueryList | null = null

  function apply(value: SiteTheme) {
    theme.value = value
    document.documentElement.dataset.siteTheme = value
    document.documentElement.style.colorScheme = value === 'ivory' ? 'light' : 'dark'
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      'content',
      value === 'ivory' ? '#f5f2ea' : '#171717',
    )
  }

  function select(value: SiteTheme) {
    followsSystem.value = false
    apply(value)
    try { window.localStorage.setItem(STORAGE_KEY, value) } catch { /* persistence is best-effort */ }
  }

  function toggle() {
    select(theme.value === 'ivory' ? 'graphite' : 'ivory')
  }

  function handleSystemChange(event: MediaQueryListEvent) {
    if (followsSystem.value) apply(event.matches ? 'ivory' : 'graphite')
  }

  apply(theme.value)

  onMounted(() => {
    query = window.matchMedia?.('(prefers-color-scheme: light)') || null
    query?.addEventListener('change', handleSystemChange)
  })

  onUnmounted(() => query?.removeEventListener('change', handleSystemChange))

  return { theme, toggle }
}
