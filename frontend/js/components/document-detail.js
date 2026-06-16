/* ==========================================================================
   文档详情组件 — 文档信息、解析元素、知识块
   ========================================================================== */

const DocumentDetail = (() => {

  let currentDoc = null;
  let elements = [];
  let chunks = [];
  let activeTab = 'elements';

  async function render(docId) {
    UI.setBreadcrumb([
      { label: '仪表盘', path: '#/' },
      { label: '文档管理', path: '#/documents' },
      { label: '文档详情' },
    ]);

    UI.render(`<div class="loading-overlay"><div class="loading-spinner"></div><span>加载文档详情…</span></div>`);

    try {
      const [doc, elems, chks] = await Promise.all([
        API.getDocument(docId),
        API.getDocumentElements(docId),
        API.getDocumentChunks(docId),
      ]);
      currentDoc = doc;
      elements = Array.isArray(elems) ? elems : (elems?.elements || []);
      chunks = Array.isArray(chks) ? chks : (chks?.chunks || []);
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
    const sourceType = doc.source_type || '';
    const title = doc.title || doc.file_name || '未命名文档';

    UI.render(`
      <!-- 文档信息头部 -->
      <div class="doc-detail-header">
        <div style="display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2);">
          ${UI.fmtBadge(sourceType)}
          <h1 class="page-title" style="margin-bottom: 0;">${UI.escapeHtml(title)}</h1>
        </div>
        <div class="doc-detail-meta">
          <div class="doc-detail-meta-item">
            ID: <strong>${UI.escapeHtml(doc.doc_id || doc.id || '—')}</strong>
          </div>
          <div class="doc-detail-meta-item">
            分类: <strong>${UI.escapeHtml(doc.category || '通用')}</strong>
          </div>
          <div class="doc-detail-meta-item">
            状态: ${UI.statusBadge(doc.status || 'active')}
          </div>
          <div class="doc-detail-meta-item">
            版本: <strong>${doc.version || 1}</strong>
          </div>
          <div class="doc-detail-meta-item">
            创建时间: <strong>${UI.formatTime(doc.created_at)}</strong>
          </div>
          <div class="doc-detail-meta-item">
            更新时间: <strong>${UI.formatTime(doc.updated_at)}</strong>
          </div>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="tabs">
        <button class="tab-item${activeTab === 'elements' ? ' active' : ''}"
                onclick="DocumentDetail.switchTab('elements')">
          解析元素 (${elements.length})
        </button>
        <button class="tab-item${activeTab === 'chunks' ? ' active' : ''}"
                onclick="DocumentDetail.switchTab('chunks')">
          知识块 (${chunks.length})
        </button>
        <button class="tab-item${activeTab === 'info' ? ' active' : ''}"
                onclick="DocumentDetail.switchTab('info')">
          文档信息
        </button>
      </div>

      <!-- 解析元素 Tab -->
      <div class="tab-content${activeTab === 'elements' ? ' active' : ''}" id="tabElements">
        ${renderElementsHtml()}
      </div>

      <!-- 知识块 Tab -->
      <div class="tab-content${activeTab === 'chunks' ? ' active' : ''}" id="tabChunks">
        ${renderChunksHtml()}
      </div>

      <!-- 文档信息 Tab -->
      <div class="tab-content${activeTab === 'info' ? ' active' : ''}" id="tabInfo">
        ${renderInfoHtml()}
      </div>
    `);
  }

  function renderElementsHtml() {
    if (elements.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <div class="empty-state-title">暂无解析元素</div>
          <div class="empty-state-desc">文档尚未完成解析，或解析未产生结构化元素。请检查入库任务状态。</div>
        </div>`;
    }

    return `
      <div class="element-list">
        ${elements.map((el, i) => `
          <div class="element-item">
            <span class="element-seq">${el.sequence_order != null ? el.sequence_order : i + 1}</span>
            <div class="element-content">
              <div class="element-text">${UI.escapeHtml(el.text || '(空)')}</div>
              <div class="element-type">
                ${UI.escapeHtml(el.element_type || 'unknown')}
                ${el.source_location?.page != null ? ` · 第 ${el.source_location.page} 页` : ''}
              </div>
            </div>
          </div>
        `).join('')}
      </div>`;
  }

  function renderChunksHtml() {
    if (chunks.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-state-icon">🧩</div>
          <div class="empty-state-title">暂无知识块</div>
          <div class="empty-state-desc">文档尚未完成语义抽取。请检查入库任务状态，确保 LLM 抽取步骤已完成。</div>
        </div>`;
    }

    return `
      <div class="chunks-grid">
        ${chunks.map(chunk => `
          <div class="chunk-card">
            <div class="chunk-card-header">
              <div class="chunk-card-title">${UI.escapeHtml(chunk.title || '未命名知识块')}</div>
              ${UI.ktypeBadge(chunk.knowledge_type)}
            </div>
            <div class="chunk-card-content">${UI.escapeHtml(chunk.content || '')}</div>
            <div class="chunk-card-footer">
              ${UI.statusBadge(chunk.index_status || 'pending')}
              <span class="tag">${UI.escapeHtml(chunk.category || '未分类')}</span>
              ${chunk.asset_refs?.length ? `<span class="tag">📎 ${chunk.asset_refs.length} 个资源</span>` : ''}
            </div>
          </div>
        `).join('')}
      </div>`;
  }

  function renderInfoHtml() {
    const doc = currentDoc || {};
    const entries = Object.entries(doc).filter(([k]) =>
      !['elements', 'chunks'].includes(k)
    );

    return `
      <div class="card">
        <table>
          <thead>
            <tr><th style="width: 30%;">字段</th><th>值</th></tr>
          </thead>
          <tbody>
            ${entries.map(([k, v]) => `
              <tr>
                <td style="font-weight: 500;">${UI.escapeHtml(k)}</td>
                <td style="font-family: var(--font-mono); font-size: var(--text-xs); word-break: break-all;">
                  ${v === null ? '<span style="color: var(--ink-wash-light);">null</span>' :
                    v === undefined ? '<span style="color: var(--ink-wash-light);">—</span>' :
                    typeof v === 'object' ? `<pre style="margin:0; white-space: pre-wrap;">${UI.escapeHtml(JSON.stringify(v, null, 2))}</pre>` :
                    UI.escapeHtml(String(v))}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>`;
  }

  function switchTab(tab) {
    activeTab = tab;
    renderDetailHtml();
  }

  return { render, switchTab };
})();
