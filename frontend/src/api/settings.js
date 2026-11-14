const BASE = '/api'

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) {
        detail = Array.isArray(body.detail)
          ? body.detail.map((item) => item.msg ?? JSON.stringify(item)).join('; ')
          : String(body.detail)
      }
    } catch {
      /* non-JSON error body: keep the status line */
    }
    throw new Error(detail)
  }

  if (response.status === 204) return null
  return response.json()
}

export const settingsApi = {
  meta: () => request('/settings/meta'),

  listProviders: () => request('/settings/providers'),
  saveProvider: (payload) =>
    request('/settings/providers', { method: 'POST', body: JSON.stringify(payload) }),
  deleteProvider: (id) => request(`/settings/providers/${id}`, { method: 'DELETE' }),
  testProvider: (id, model) =>
    request(`/settings/providers/${id}/test`, {
      method: 'POST',
      body: JSON.stringify({ model: model || null }),
    }),

  listTasks: () => request('/settings/tasks'),
  saveTask: (taskName, payload) =>
    request(`/settings/tasks/${taskName}`, { method: 'PUT', body: JSON.stringify(payload) }),
}

export const healthApi = {
  check: () => request('/health'),
}
