/* ==========================================================================
   文档详情组件 — 概览、知识块、解析元素、元数据（已迁移至 v1 API）
   ========================================================================== */

const DocumentDetail = (() => {

  let currentDoc = null;
  let elements = [];
  let chunks = [];
  let activeTab = 'overview';

  async function render(docId) {
    UI.setBreadcrumb([
      { label: '仪表盘', path: '#/' },
      { label: '文档管理', path: '#/documents' },
      { label: '文档详情' },
    ]);

    UI.render(`<div class="loading-overlay"><div class="loading-spinner"></div><span>加载文档详情…</span></div>`);

    try {
      const [docRes, chunksRes] = await Promise.all([
        API.getDocument(docId),
        API.listChunks({ doc_id: docId, page_size: 200 }),
      ]);
      currentDoc = docRes?.data || {};
      chunks = chunksRes?.data || [];
      elements = [];
    } catch (e) {
      UI.render(`
        <div class="empty-state">
          <div class="empty-state-icon">⚠</div>
          <div class="empty-state-title">加载失败</div>
          <div class="empty-state-desc">${UI.escapeHtml(e.message)}</div>
          <button class="btn btn-secondary" onclick="history.back()" style="margin-top: var(--space-4);">← 返回</button>
        </div>
      `);
      return;
    }

    renderDetailHtml();
  }

  function renderDetailHtml() {
    const doc = currentDoc || {};
    const title = doc.title || '未命名文档';
    const stats = doc.index_summary || {};

    UI.render(`
      <!-- 文档信息头部 -->
      <div class="doc-detail-header">
        <div class="page-header-row">
          <div class="doc-heading">
            ${UI.fmtBadge(doc.source_type)}
            <h1 class="page-title" style="margin-bottom: 0;">${UI.escapeHtml(title)}</h1>
            ${UI.statusBadge(doc.status || 'active')}
          </div>
          <div class="page-actions">
            <button class="btn btn-secondary btn-sm" onclick="Documents.ingestDocument('${doc.doc_id}')">↻ 重新入库</button>
            ${doc.status === 'deleted'
              ? `<button class="btn btn-success btn-sm" onclick="Documents.restoreDoc('${doc.doc_id}')">恢复文档</button>`
              : `<button class="btn btn-danger btn-sm" onclick="Documents.deleteDoc('${doc.doc_id}')">删除文档</button>`}
          </div>
        </div>
        <div class="doc-detail-meta">
          <div class="doc-detail-meta-item">ID: <strong>${UI.escapeHtml(doc.doc_id || '—')}</strong></div>
          <div class="doc-detail-meta-item">分类: <strong>${UI.escapeHtml(doc.category || '通用')}</strong></div>
          <div class="doc-detail-meta-item">版本: <strong>${doc.version || 1}</strong></div>
          <div class="doc-detail-meta-item">创建: <strong>${UI.formatTime(doc.created_at)}</strong></div>
          <div class="doc-detail-meta-item">更新: <strong>${UI.formatTime(doc.updated_at)}</strong></div>
        </div>
        <!-- 统计快览 -->
        <div class="mini-stats-row">
          <div class="stat-mini"><span class="stat-mini-num">${doc.chunk_count ?? chunks.length}</span><span class="stat-mini-label">知识块</span></div>
          <div class="stat-mini"><span class="stat-mini-num">${doc.element_count ?? '—'}</span><span class="stat-mini-label">解析元素</span></div>
          <div class="stat-mini"><span class="stat-mini-num">${doc.asset_count ?? '—'}</span><span class="stat-mini-label">资源</span></div>
          <div class="stat-mini"><span class="stat-mini-num" style="color: var(--jade);">${stats.indexed || 0}</span><span class="stat-mini-label">已索引</span></div>
          <div class="stat-mini"><span class="stat-mini-num" style="color: var(--cinnabar);">${stats.failed || 0}</span><span class="stat-mini-label">索引失败</span></div>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="tabs">
        <button class="tab-item${activeTab === 'overview' ? ' active' : ''}" onclick="DocumentDetail.switchTab('overview')">概览</button>
        <button class="tab-item${activeTab === 'chunks' ? ' active' : ''}" onclick="DocumentDetail.switchTab('chunks')">知识块 (${chunks.length})</button>
        <button class="tab-item${activeTab === 'elements' ? ' active' : ''}" onclick="DocumentDetail.switchTab('elements')">解析元素 (${elements.length})</button>
        <button class="tab-item${activeTab === 'meta' ? ' active' : ''}" onclick="DocumentDetail.switchTab('meta')">元数据</button>
      </div>

      <div class="tab-content${activeTab === 'overview' ? ' active' : ''}" id="tabOverview">${renderOverviewHtml()}</div>
      <div class="tab-content${activeTab === 'chunks' ? ' active' : ''}" id="tabChunks">${renderChunksHtml()}</div>
      <div class="tab-content${activeTab === 'elements' ? ' active' : ''}" id="tabElements">${renderElementsHtml()}</div>
      <div class="tab-content${activeTab === 'meta' ? ' active' : ''}" id="tabMeta">${renderMetaHtml()}</div>
    `);
  }

  function renderOverviewHtml() {
    const doc = currentDoc || {};
    return `
      <div class="card">
        <h3 class="card-title">文档信息</h3>
        <table>
          <tbody>
            <tr><td style="font-weight:500;">来源 URI</td><td style="font-family: var(--font-mono); font-size: var(--text-xs); word-break: break-all;">${UI.escapeHtml(doc.source_uri || '—')}</td></tr>
            <tr><td style="font-weight:500;">来源哈希</td><td style="font-family: var(--font-mono); font-size: var(--text-xs);">${UI.escapeHtml(doc.source_hash || '—')}</td></tr>
            <tr><td style="font-weight:500;">父文档</td><td>${UI.escapeHtml(doc.parent_doc_id || '—')}</td></tr>
            <tr><td style="font-weight:500;">根文档</td><td>${UI.escapeHtml(doc.root_doc_id || '—')}</td></tr>
            <tr><td style="font-weight:500;">入库任务</td><td style="font-family: var(--font-mono); font-size: var(--text-xs);">${UI.escapeHtml(doc.ingest_job_id || '—')}</td></tr>
          </tbody>
        </table>
      </div>`;
  }

  function renderChunksHtml() {
    if (chunks.length === 0) {
      return `<div class="empty-state"><div class="empty-state-icon">🧩</div><div class="empty-state-title">暂无知识块</div></div>`;
    }
    return `
      <div class="chunks-grid">
        ${chunks.map(chunk => `
          <div class="chunk-card">
            <div class="chunk-card-header">
              <div class="chunk-card-title">${UI.escapeHtml(chunk.title || '未命名知识块')}</div>
              ${UI.ktypeBadge(chunk.knowledge_type)}
            </div>
            <div class="chunk-card-content">${UI.escapeHtml((chunk.content_preview || chunk.content || '').substring(0, 300))}</div>
            <div class="chunk-card-footer">
              ${UI.statusBadge(chunk.index_status || 'pending')}
              <span class="tag">${UI.escapeHtml(chunk.category || '未分类')}</span>
              ${(chunk.asset_count || 0) > 0 ? `<span class="tag">📎 ${chunk.asset_count} 个资源</span>` : ''}
              ${(chunk.source_count || 0) > 0 ? `<span class="tag">📄 ${chunk.source_count} 个来源</span>` : ''}
            </div>
          </div>
        `).join('')}
      </div>`;
  }

  function renderElementsHtml() {
    if (elements.length === 0) {
      return `<div class="empty-state"><div class="empty-state-icon">📋</div><div class="empty-state-title">暂无解析元素（需在后端 PG 模式下查看）</div></div>`;
    }
    return `
      <div class="element-list">
        ${elements.map((el, i) => `
          <div class="element-item">
            <span class="element-seq">${el.sequence_order != null ? el.sequence_order : i + 1}</span>
            <div class="element-content">
              <div class="element-text">${UI.escapeHtml(el.text || '(空)')}</div>
              <div class="element-type">${UI.escapeHtml(el.element_type || 'unknown')} ${el.source_location?.page != null ? `· 第 ${el.source_location.page} 页` : ''}</div>
            </div>
          </div>
        `).join('')}
      </div>`;
  }

  function renderMetaHtml() {
    const doc = currentDoc || {};
    return `
      <div class="card">
        <h3 class="card-title">元数据</h3>
        <pre class="code-block">${UI.escapeHtml(JSON.stringify(doc.metadata || {}, null, 2))}</pre>
      </div>
      <div class="card" style="margin-top: var(--space-4);">
        <h3 class="card-title">索引摘要</h3>
        <pre class="code-block">${UI.escapeHtml(JSON.stringify(doc.index_summary || {}, null, 2))}</pre>
      </div>`;
  }

  function switchTab(tab) {
    activeTab = tab;
    renderDetailHtml();
  }

  return { render, switchTab };
})();
