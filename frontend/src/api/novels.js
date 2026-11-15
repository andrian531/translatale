import { request, requestForm } from './client'

export const novelsApi = {
  list: () => request('/novels'),
  get: (id) => request(`/novels/${id}`),
  create: (payload) =>
    request('/novels', { method: 'POST', body: JSON.stringify(payload) }),
  createFromUrl: (payload) =>
    request('/novels/from-url', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id, payload) =>
    request(`/novels/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  remove: (id) => request(`/novels/${id}`, { method: 'DELETE' }),

  listChapters: (id, status) =>
    request(`/novels/${id}/chapters${status ? `?status=${status}` : ''}`),
  addManualChapter: (id, payload) =>
    request(`/novels/${id}/chapters/manual`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  fetchChapters: (id, chapterIds) =>
    request(`/novels/${id}/chapters/fetch`, {
      method: 'POST',
      body: JSON.stringify({ chapter_ids: chapterIds }),
    }),
  addChaptersFromUrl: (id, urls) =>
    request(`/novels/${id}/chapters/from-url`, {
      method: 'POST',
      body: JSON.stringify({ urls }),
    }),
  syncNovelChapters: (id, sourceUrl) =>
    request(`/novels/${id}/chapters/sync-url`, {
      method: 'POST',
      body: JSON.stringify(sourceUrl ? { source_url: sourceUrl } : {}),
    }),
  startFetchJob: (id, { chapterIds = [], limit = null } = {}) =>
    request(`/novels/${id}/chapters/fetch-job`, {
      method: 'POST',
      body: JSON.stringify({ chapter_ids: chapterIds, limit }),
    }),
  uploadChapters: (id, files) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    return requestForm(`/novels/${id}/chapters/upload`, form)
  },

  getChapter: (chapterId) => request(`/chapters/${chapterId}`),
  updateChapter: (chapterId, payload) =>
    request(`/chapters/${chapterId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  removeChapter: (chapterId) => request(`/chapters/${chapterId}`, { method: 'DELETE' }),
}
