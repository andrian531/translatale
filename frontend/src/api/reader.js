import { request } from './client'

export const readerApi = {
  getProgress: (novelId) => request(`/novels/${novelId}/progress`),
  saveProgress: (novelId, payload) =>
    request(`/novels/${novelId}/progress`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  /** Direct download URL (the browser handles the attachment). */
  exportUrl: (novelId, format) => `/api/novels/${novelId}/export?format=${format}`,
}
