const BASE = '/api'

async function parseError(response) {
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
  return detail
}

export async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!response.ok) throw new Error(await parseError(response))
  if (response.status === 204) return null
  return response.json()
}

/** Multipart upload: the browser must set the boundary, so no Content-Type. */
export async function requestForm(path, formData) {
  const response = await fetch(`${BASE}${path}`, { method: 'POST', body: formData })
  if (!response.ok) throw new Error(await parseError(response))
  return response.json()
}
