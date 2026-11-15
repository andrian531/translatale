/**
 * Tiny i18n layer — no dependencies.
 *
 * `t()` reads `locale` at call time, so any template or computed that calls it
 * re-renders when the language changes. Missing keys fall back to English and
 * then to the key itself, which makes a half-migrated view obvious instead of
 * silently blank.
 */
import { ref } from 'vue'
import en from './en'
import id from './id'

export const STORAGE_KEY = 'translatale:locale'
export const LOCALES = ['en', 'id']
export const DEFAULT_LOCALE = 'en'

function readInitial() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (LOCALES.includes(stored)) return stored
  } catch {
    /* private mode / storage disabled */
  }
  return DEFAULT_LOCALE
}

export const locale = ref(readInitial())

function lookup(dict, key) {
  return key
    .split('.')
    .reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), dict)
}

function interpolate(text, params) {
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    params[name] === undefined || params[name] === null ? match : String(params[name]),
  )
}

export function t(key, params) {
  const dict = locale.value === 'id' ? id : en
  let value = lookup(dict, key)
  if (value === undefined) value = lookup(en, key)
  if (value === undefined) return key
  return interpolate(String(value), params)
}

export function setLocale(next) {
  if (!LOCALES.includes(next)) return
  locale.value = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* ignore */
  }
  document.documentElement.setAttribute('lang', next)
}

export function initLocale() {
  document.documentElement.setAttribute('lang', locale.value)
}

export function useI18n() {
  return { locale, setLocale, t, locales: LOCALES }
}
