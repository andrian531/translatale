import { request } from './client'

export const translationApi = {
  getReference: (novelId) => request(`/novels/${novelId}/reference`),
  saveReference: (novelId, payload) =>
    request(`/novels/${novelId}/reference`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  applyReference: (novelId, chapterIds = null) =>
    request(`/novels/${novelId}/reference/apply`, {
      method: 'POST',
      body: JSON.stringify({ chapter_ids: chapterIds?.length ? chapterIds : null }),
    }),

  startAnalyze: (novelId, chapterIds) =>
    request(`/novels/${novelId}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ chapter_ids: chapterIds?.length ? chapterIds : null }),
    }),
  startTranslate: (novelId, chapterIds, autoUpdateReference = true) =>
    request(`/novels/${novelId}/translate`, {
      method: 'POST',
      body: JSON.stringify({
        chapter_ids: chapterIds,
        auto_update_reference: autoUpdateReference,
      }),
    }),

  getJob: (jobId) => request(`/jobs/${jobId}`),
  cancelJob: (jobId) => request(`/jobs/${jobId}/cancel`, { method: 'POST' }),
  listJobs: (novelId) => request(`/novels/${novelId}/jobs`),

  /**
   * Stream job progress over SSE. Returns a close function.
   * `onEvent` fires for every event; `onDone` fires once on a terminal event.
   */
  subscribeJob(jobId, { onEvent, onDone, onError } = {}) {
    const source = new EventSource(`/api/jobs/${jobId}/events`)

    source.onmessage = (message) => {
      let data
      try {
        data = JSON.parse(message.data)
      } catch {
        return
      }
      onEvent?.(data)
      if (['done', 'error', 'cancelled'].includes(data.type)) {
        source.close()
        onDone?.(data)
      }
    }

    source.onerror = () => {
      source.close()
      onError?.()
    }

    return () => source.close()
  },
}
