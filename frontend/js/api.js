/* ==========================================================================
   API 客户端 — 封装所有后端 API 调用
   ========================================================================== */

const API = (() => {
  const BASE = '';

  /**
   * 通用请求封装
   */
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
      const res = await fetch(url, {
        method,
        headers,
        body: reqBody,
        signal: controller.signal,
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => '');
        let errMsg = `HTTP ${res.status}`;
        try {
          const errJson = JSON.parse(errText);
          errMsg = errJson.detail || errJson.message || errMsg;
        } catch (e) { /* ignore */ }
        throw new Error(errMsg);
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

  /** GET 请求 */
  function get(path, opts) { return request('GET', path, opts); }

  /** POST 请求 */
  function post(path, body, opts) { return request('POST', path, { ...opts, body }); }

  /* -----------------------------------------------------------------------
     健康检查
     ----------------------------------------------------------------------- */
  async function healthCheck() {
    return get('/health');
  }

  /* -----------------------------------------------------------------------
     文件上传
     ----------------------------------------------------------------------- */
  async function uploadFile(file, title, category) {
    const fd = new FormData();
    fd.append('file', file);
    if (title) fd.append('title', title);
    if (category) fd.append('category', category);
    return post('/upload', fd, { timeout: 120000 });
  }

  /* -----------------------------------------------------------------------
     入库任务
     ----------------------------------------------------------------------- */
  async function submitIngest(documents, options = {}) {
    return post('/ingest', { documents, options }, { timeout: 60000 });
  }

  async function getIngestJob(jobId) {
    return get(`/ingest/${jobId}`);
  }

  /* -----------------------------------------------------------------------
     搜索
     ----------------------------------------------------------------------- */
  async function search(query, topK = 5, filters = {}) {
    return post('/search', {
      query,
      top_k: topK,
      filters,
    }, { timeout: 60000 });
  }

  /* -----------------------------------------------------------------------
     文档（需要后端配合 — 目前通过内存/DB 存储）
     以下接口在 phase 5+ 可替换为真实文档列表 API
     ----------------------------------------------------------------------- */

  /**
   * 获取文档列表 — 目前通过解析 uploads 目录 + 内存状态获取。
   * 后续可替换为 GET /documents API。
   */
  async function listDocuments() {
    // 如果有后端文档列表接口，替换这里
    // return get('/documents');
    return get('/documents');
  }

  async function getDocument(docId) {
    return get(`/documents/${docId}`);
  }

  async function getDocumentElements(docId) {
    return get(`/documents/${docId}/elements`);
  }

  async function getDocumentChunks(docId) {
    return get(`/documents/${docId}/chunks`);
  }

  /* -----------------------------------------------------------------------
     公开 API
     ----------------------------------------------------------------------- */
  return {
    healthCheck,
    uploadFile,
    submitIngest,
    getIngestJob,
    search,
    listDocuments,
    getDocument,
    getDocumentElements,
    getDocumentChunks,
  };
})();
