import { readonly, ref } from 'vue'
import simplified from './locales/zh-CN.json'
import traditional from './locales/zh-TW.json'
import japanese from './locales/ja.json'
import english from './locales/en.json'

export const UI_LANGUAGES = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'ja', label: '日本語' },
  { value: 'en', label: 'English' },
] as const
export type UiLanguage = typeof UI_LANGUAGES[number]['value']
export const LANGUAGE_NAMESPACE = 'core.language'
const current = ref<UiLanguage>('zh-CN')
let languageRevision = 0
export const uiLanguage = readonly(current)
const catalogs: Record<UiLanguage, Record<string, string>> = {
  'zh-CN': simplified, 'zh-TW': traditional, ja: japanese, en: english,
}
export function isUiLanguage(value: unknown): value is UiLanguage {
  return UI_LANGUAGES.some((item) => item.value === value)
}
export function setUiLanguage(value: unknown): void {
  languageRevision++
  current.value = isUiLanguage(value) ? value : 'zh-CN'
  if (typeof document !== 'undefined') document.documentElement.lang = current.value
}
/** Exact source keys: values supplied by users or models are never passed here. */
export function t(source: string, params: Record<string, unknown> = {}): string {
  const text = catalogs[current.value][source] ?? catalogs['zh-CN'][source] ?? source
  return text.replace(/\{(\w+)\}/g, (match, key: string) => Object.hasOwn(params, key) ? String(params[key]) : match)
}
export function defaultUiText(value: string, source: string): string
export function defaultUiText(value: string | undefined, source: string): string | undefined
export function defaultUiText(value: string | undefined, source: string): string | undefined {
  return value === source ? t(source) : value
}
export async function loadUiLanguage(requestRpc: (method: string, params: Record<string, unknown>) => Promise<Record<string, unknown>>): Promise<void> {
  const revision = languageRevision
  const result = await requestRpc('settings.get', { namespace: LANGUAGE_NAMESPACE })
  const value = result.value as { locale?: unknown } | undefined
  if (revision === languageRevision) setUiLanguage(value?.locale)
}
export async function saveUiLanguage(requestRpc: (method: string, params: Record<string, unknown>) => Promise<Record<string, unknown>>, locale: unknown): Promise<void> {
  if (!isUiLanguage(locale)) throw new Error('Unsupported interface language')
  // Change the interface only after persistence succeeds; failed saves keep
  // the current language and unsaved settings form intact.
  await requestRpc('settings.update', { namespace: LANGUAGE_NAMESPACE, value: { locale } })
  setUiLanguage(locale)
}
