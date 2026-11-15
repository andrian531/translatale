import { request } from './client'

export const settingsApi = {
  meta: () => request('/settings/meta'),

  listProviders: () => request('/settings/providers'),
  saveProvider: (payload) =>
    request('/settings/providers', { method: 'POST', body: JSON.stringify(payload) }),
  previewProvider: (payload) =>
    request('/settings/providers/preview', { method: 'POST', body: JSON.stringify(payload) }),
  deleteProvider: (id) => request(`/settings/providers/${id}`, { method: 'DELETE' }),
  testProvider: (id, model) =>
    request(`/settings/providers/${id}/test`, {
      method: 'POST',
      body: JSON.stringify({ model: model || null }),
    }),

  listTasks: () => request('/settings/tasks'),
  saveTask: (taskName, payload) =>
    request(`/settings/tasks/${taskName}`, { method: 'PUT', body: JSON.stringify(payload) }),

  syncProviderModels: (id) =>
    request(`/settings/providers/${id}/models/sync`, { method: 'POST' }),

  getScraperSettings: () => request('/settings/scraper'),
  saveScraperSettings: (payload) =>
    request('/settings/scraper', { method: 'PUT', body: JSON.stringify(payload) }),
}

export const healthApi = {
  check: () => request('/health'),
}
