import { request } from './client'

export const scrapersApi = {
  list: () => request('/scrapers'),
  preview: (url) =>
    request('/scrapers/preview', { method: 'POST', body: JSON.stringify({ url }) }),
  analyze: (url, htmlSnippet) =>
    request('/scrapers/analyze', {
      method: 'POST',
      body: JSON.stringify({ url, html_snippet: htmlSnippet || null }),
    }),
}
