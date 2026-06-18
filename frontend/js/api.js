/* ==========================================================================
   API 客户端 — 封装所有后端 API 调用（主版本 v1）

   前端所有功能统一使用 v1 接口；旧版接口仅由后端保留兼容期。
   ========================================================================== */

const API = (() => {
  const BASE = '';

  /* -----------------------------------------------------------------------
     通用请求封装
     ----------------------------------------------------------------------- */
  function toQueryString(params = {}) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      if (Array.isArray(value)) {
        value.forEach(item => {
          if (item !== undefined && item !== null) qs.append(key, item);
        });
        return;
      }
      qs.append(key, value);
    });
    return qs.toString();
  }

  function withParams(path, params) {
    const qs = toQueryString(params);
    if (!qs) return path;
    return `${path}${path.includes('?') ? '&' : '?'}${qs}`;
  }

  async function request(method, path, opts = {}) {
    const { body, params, timeout = 30000 } = opts;
    const url = `${BASE}${withParams(path, params)}`;

    const headers = {};
    let reqBody = null;

    if (body) {
      if (body instanceof FormData) {
        reqBody = body;
      } else {
        headers['Content-Type'] = 'application/json';
        reqBody = JSON.stringify(body);
      }
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
      const res = await fetch(url, { method, headers, body: reqBody, signal: controller.signal });

      if (!res.ok) {
        const errText = await res.text().catch(() => '');
        let errMsg = `HTTP ${res.status}`;
        try {
          const errJson = JSON.parse(errText);
          // 兼容 v1 统一错误结构 { error: { message } } 和旧结构 { detail }
          errMsg = errJson?.error?.message || errJson?.detail || errJson?.message || errMsg;
        } catch (e) { /* ignore */ }
        throw new Error(errMsg);
      }

      // 检查废弃响应头
      const deprecated = res.headers.get('X-Deprecated');
      if (deprecated) {
        console.warn(`[API] 调用了已废弃的接口: ${method} ${path} — ${deprecated}`);
      }

      const text = await res.text();
      if (!text.trim()) return null;
      return JSON.parse(text);
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error('请求超时，请稍后重试');
      }
      if (err instanceof TypeError && (err.message === 'Failed to fetch' || err.message.includes('NetworkError'))) {
        throw new Error('无法连接后端服务，请确认服务已启动后重试。');
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  function get(path, opts) { return request('GET', path, opts); }
  function post(path, body, opts) { return request('POST', path, { ...opts, body }); }

  /* =======================================================================
     API v1 — 健康检查（主版本）
     ======================================================================= */
  async function healthLive()     { return get('/api/v1/health/live'); }
  async function healthReady()    { return get('/api/v1/health/ready'); }
  async function healthDependencies() { return get('/api/v1/health/dependencies'); }

  /* =======================================================================
     API v1 — 文档管理（主版本）
     ======================================================================= */
  async function listDocuments(params = {}) {
    return get('/api/v1/documents', { params });
  }
  async function createDocument(params) {
    return post('/api/v1/documents', null, { params });
  }
  async function getDocument(docId) {
    return get(`/api/v1/documents/${docId}`);
  }
  async function listDocumentElements(docId, params = {}) {
    return get(`/api/v1/documents/${docId}/elements`, { params });
  }
  async function updateDocument(docId, params) {
    return request('PATCH', `/api/v1/documents/${docId}`, { params, timeout: 30000 });
  }
  async function deleteDocument(docId) {
    return request('DELETE', `/api/v1/documents/${docId}`, { timeout: 30000 });
  }
  async function restoreDocument(docId) {
    return post(`/api/v1/documents/${docId}/restore`);
  }
  async function ingestDocument(docId, mode = 'incremental') {
    return post(`/api/v1/documents/${docId}/ingest`, null, { params: { mode } });
  }
  async function uploadDocument(file, title = '', category = '通用', options = {}) {
    const fd = new FormData();
    fd.append('file', file);
    if (title) fd.append('title', title);
    if (category) fd.append('category', category);
    const params = {
      ingest_after_create: options.ingestAfterCreate !== false,
      mode: options.mode || 'incremental',
    };
    return post('/api/v1/documents/upload', fd, { params, timeout: 120000 });
  }
  async function listIngestJobs(params = {}) {
    return get('/api/v1/ingest/jobs', { params });
  }
  async function getIngestJobV1(jobId) {
    return get(`/api/v1/ingest/jobs/${jobId}`);
  }
  async function retryIngestJob(jobId) {
    return post(`/api/v1/ingest/jobs/${jobId}/retry`);
  }
  async function cancelIngestJob(jobId) {
    return post(`/api/v1/ingest/jobs/${jobId}/cancel`);
  }

  /* =======================================================================
     API v1 — 知识块管理（主版本）
     ======================================================================= */
  async function listChunks(params = {}) { return get('/api/v1/chunks', { params }); }
  async function createChunk(params)     { return post('/api/v1/chunks', null, { params }); }
  async function getChunk(chunkId)       { return get(`/api/v1/chunks/${chunkId}`); }
  async function updateChunk(chunkId, params) {
    return request('PATCH', `/api/v1/chunks/${chunkId}`, { params, timeout: 30000 });
  }
  async function deleteChunk(chunkId) {
    return request('DELETE', `/api/v1/chunks/${chunkId}`, { timeout: 30000 });
  }
  async function restoreChunk(chunkId) {
    return post(`/api/v1/chunks/${chunkId}/restore`);
  }
  async function reindexChunk(chunkId) {
    return post(`/api/v1/chunks/${chunkId}/reindex`);
  }
  async function batchReindexChunks(chunkIds) {
    return post('/api/v1/chunks/batch/reindex', { chunk_ids: chunkIds });
  }
  async function batchChunkOperation(action, chunkIds, status = null) {
    return post('/api/v1/chunks/batch', { action, chunk_ids: chunkIds, status });
  }

  /* =======================================================================
     API v1 — 检索（主版本）
     ======================================================================= */
  async function search(query, topK = 10, filters = {}, options = {}) {
    return post('/api/v1/search', { query, top_k: topK, filters, options }, { timeout: 60000 });
  }
  async function searchDebug(query, topK = 10, filters = {}) {
    return post('/api/v1/search/debug', { query, top_k: topK, filters }, { timeout: 60000 });
  }
  async function searchFilters() { return get('/api/v1/search/filters'); }

  /* =======================================================================
     公开 API — v1 方法为默认导出
     ======================================================================= */
  return {
    // ── v1 健康检查 ──
    healthLive, healthReady, healthDependencies,
    // ── v1 文档 ──
    listDocuments, createDocument, getDocument, listDocumentElements, updateDocument,
    deleteDocument, restoreDocument, ingestDocument, uploadDocument,
    listIngestJobs, getIngestJobV1, retryIngestJob, cancelIngestJob,
    // ── v1 知识块 ──
    listChunks, createChunk, getChunk, updateChunk,
    deleteChunk, restoreChunk, reindexChunk,
    batchReindexChunks, batchChunkOperation,
    // ── v1 检索 ──
    search, searchDebug, searchFilters,
  };
})();
