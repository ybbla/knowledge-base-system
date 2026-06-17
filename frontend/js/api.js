/* ==========================================================================
   API 客户端 — 封装所有后端 API 调用（主版本 v1）

   旧版接口（/health, /upload, /ingest, /search, /documents）已标记废弃，
   保留以供兼容。所有新功能请使用 v1 接口。
   ========================================================================== */

const API = (() => {
  const BASE = '';

  /* -----------------------------------------------------------------------
     通用请求封装
     ----------------------------------------------------------------------- */
  async function request(method, path, opts = {}) {
    const { body, params, timeout = 30000 } = opts;
    let url = `${BASE}${path}`;

    if (params) {
      const qs = new URLSearchParams(params).toString();
      url += `?${qs}`;
    }

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
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  function get(path, opts) { return request('GET', path, opts); }
  function post(path, body, opts) { return request('POST', path, { ...opts, body }); }

  // 废弃标记辅助
  function _deprecated(oldFn, name, replacement) {
    return async function (...args) {
      console.warn(`[API] ${name} 已废弃，请迁移到 ${replacement}`);
      return oldFn(...args);
    };
  }

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
  async function updateDocument(docId, params) {
    let url = `/api/v1/documents/${docId}`;
    if (params) { url += `?${new URLSearchParams(params)}`; }
    return request('PATCH', url, { timeout: 30000 });
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

  /* =======================================================================
     API v1 — 知识块管理（主版本）
     ======================================================================= */
  async function listChunks(params = {}) { return get('/api/v1/chunks', { params }); }
  async function createChunk(params)     { return post('/api/v1/chunks', null, { params }); }
  async function getChunk(chunkId)       { return get(`/api/v1/chunks/${chunkId}`); }
  async function updateChunk(chunkId, params) {
    let url = `/api/v1/chunks/${chunkId}`;
    if (params) { url += `?${new URLSearchParams(params)}`; }
    return request('PATCH', url, { timeout: 30000 });
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
    const qs = new URLSearchParams();
    chunkIds.forEach(id => qs.append('chunk_ids', id));
    return post(`/api/v1/chunks/batch/reindex?${qs.toString()}`);
  }
  async function batchChunkOperation(action, chunkIds, status = null) {
    const qs = new URLSearchParams();
    qs.append('action', action);
    chunkIds.forEach(id => qs.append('chunk_ids', id));
    if (status) qs.append('status', status);
    return post(`/api/v1/chunks/batch?${qs.toString()}`);
  }

  /* =======================================================================
     API v1 — 检索（主版本）
     ======================================================================= */
  async function search(query, topK = 10, filters = {}, options = {}) {
    return post('/api/v1/search', { query, top_k: topK, filters, options }, { timeout: 60000 });
  }
  async function searchPreview(query, topK = 10, filters = {}) {
    return post('/api/v1/search/preview', {
      query, top_k: topK, filters, options: { rerank: false },
    }, { timeout: 30000 });
  }
  async function searchDebug(query, topK = 10, filters = {}) {
    return post('/api/v1/search/debug', { query, top_k: topK, filters }, { timeout: 60000 });
  }
  async function searchFilters() { return get('/api/v1/search/filters'); }
  async function searchFeedback(chunkId, feedback, searchId = '') {
    return post('/api/v1/search/feedback', { chunk_id: chunkId, feedback, search_id: searchId });
  }

  /* =======================================================================
     旧版 API — 保留兼容，已废弃（将在后续版本移除）
     ======================================================================= */

  /** @deprecated 使用 API.healthLive() / API.healthReady() 代替 */
  async function _oldHealthCheck() { return get('/health'); }

  /** @deprecated 使用 API.createDocument() + API.ingestDocument() 代替 */
  async function _oldUploadFile(file, title, category) {
    const fd = new FormData();
    fd.append('file', file);
    if (title) fd.append('title', title);
    if (category) fd.append('category', category);
    return post('/upload', fd, { timeout: 120000 });
  }

  /** @deprecated 使用 API.ingestDocument() 代替 */
  async function _oldSubmitIngest(documents, options = {}) {
    return post('/ingest', { documents, options }, { timeout: 60000 });
  }

  /** @deprecated 使用 /api/v1 的入库任务查询代替 */
  async function _oldGetIngestJob(jobId) { return get(`/ingest/${jobId}`); }

  /** @deprecated 使用 API.getDocument() 代替 */
  async function _oldGetDocument(docId) { return get(`/documents/${docId}`); }

  /** @deprecated 使用 /api/v1/documents 代替 */
  async function _oldGetDocumentElements(docId) { return get(`/documents/${docId}/elements`); }

  /** @deprecated 使用 API.listChunks() 代替 */
  async function _oldGetDocumentChunks(docId) { return get(`/documents/${docId}/chunks`); }

  /* =======================================================================
     公开 API — v1 方法为默认导出
     ======================================================================= */
  return {
    // ── v1 健康检查 ──
    healthLive, healthReady, healthDependencies,
    // ── v1 文档 ──
    listDocuments, createDocument, getDocument, updateDocument,
    deleteDocument, restoreDocument, ingestDocument,
    // ── v1 知识块 ──
    listChunks, createChunk, getChunk, updateChunk,
    deleteChunk, restoreChunk, reindexChunk,
    batchReindexChunks, batchChunkOperation,
    // ── v1 检索 ──
    search, searchPreview, searchDebug, searchFilters, searchFeedback,

    // ── 旧版兼容（废弃，控制台会输出警告） ──
    healthCheck:       _deprecated(_oldHealthCheck, 'healthCheck()', 'healthLive() / healthReady()'),
    uploadFile:        _deprecated(_oldUploadFile, 'uploadFile()', 'createDocument() + ingestDocument()'),
    submitIngest:      _deprecated(_oldSubmitIngest, 'submitIngest()', 'ingestDocument()'),
    getIngestJob:      _deprecated(_oldGetIngestJob, 'getIngestJob()', 'v1 入库任务接口'),
    getDocumentElements: _deprecated(_oldGetDocumentElements, 'getDocumentElements()', 'v1 文档详情接口'),
    getDocumentChunks: _deprecated(_oldGetDocumentChunks, 'getDocumentChunks()', 'listChunks()'),

    // 别名（旧代码引用旧方法名时的平滑过渡）
    v1ListDocuments: listDocuments,
    v1CreateDocument: createDocument,
    v1GetDocument: getDocument,
    v1UpdateDocument: updateDocument,
    v1DeleteDocument: deleteDocument,
    v1RestoreDocument: restoreDocument,
    v1IngestDocument: ingestDocument,
    v1ListChunks: listChunks,
    v1CreateChunk: createChunk,
    v1GetChunk: getChunk,
    v1UpdateChunk: updateChunk,
    v1DeleteChunk: deleteChunk,
    v1RestoreChunk: restoreChunk,
    v1ReindexChunk: reindexChunk,
    v1BatchReindexChunks: batchReindexChunks,
    v1BatchChunkOperation: batchChunkOperation,
    v1Search: search,
    v1SearchPreview: searchPreview,
    v1SearchDebug: searchDebug,
    v1SearchFilters: searchFilters,
    v1SearchFeedback: searchFeedback,
    v1HealthLive: healthLive,
    v1HealthReady: healthReady,
    v1HealthDependencies: healthDependencies,
  };
})();
