/**
 * Global Dark / Light theme.
 *
 * The class lives on <html> so the CSS custom properties in style.css can flip
 * every surface at once. ReaderView keeps its own reading theme (light/sepia/
 * dark) — that one is scoped to the reader and must not be touched here.
 */
import { ref } from 'vue'

export const STORAGE_KEY = 'translatale:theme'
export const THEMES = ['dark', 'light']
export const DEFAULT_THEME = 'dark'

function readInitial() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (THEMES.includes(stored)) return stored
  } catch {
    /* private mode / storage disabled */
  }
  return DEFAULT_THEME
}

export const theme = ref(readInitial())

function apply(value) {
  const root = document.documentElement
  root.classList.toggle('light', value === 'light')
  root.classList.toggle('dark', value === 'dark')
  root.style.colorScheme = value
}

export function setTheme(next) {
  if (!THEMES.includes(next)) return
  theme.value = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* ignore */
  }
  apply(next)
}

export function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

/** Apply the stored theme before the first paint. */
export function initTheme() {
  apply(theme.value)
}

export function useTheme() {
  return { theme, setTheme, toggleTheme, themes: THEMES }
}
