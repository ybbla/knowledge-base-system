/* ==========================================================================
   搜索页面组件 — 混合检索（v1 API），含过滤面板、结果详情、检索调试
   ========================================================================== */

const SearchPage = (() => {

  let lastResult = null;
  let lastQuery = '';
  let pendingTopKSelectId = '';

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '知识搜索' }]);

    // 加载筛选项
    let filterOptions = {};
    try {
      const res = await API.searchFilters();
      filterOptions = res?.data || {};
    } catch (e) { /* ignore */ }

    UI.render(`
      <div class="page-header">
        <h1 class="page-title">知识搜索</h1>
        <p class="page-subtitle">向量 + BM25 + RRF 融合检索，支持多维过滤</p>
      </div>

      <div class="search-panel kb-query-panel">
        <div class="kb-query-main">
          <div class="search-input-wrap">
            <span class="search-input-icon">⌕</span>
            <input class="input input-lg" type="text" id="searchInput" placeholder="输入问题，检索最相关的知识块…" autofocus
                   onkeydown="if(event.key==='Enter')SearchPage.doSearch()">
          </div>
          <button class="btn btn-primary" onclick="SearchPage.doSearch()">搜索</button>
        </div>

        <div class="search-filters kb-filter-bar">
          <select id="searchCategory" class="select select-sm">
            <option value="">全部分类</option>
            ${(filterOptions.categories || []).map(c => `<option value="${UI.escapeHtml(c.value)}">${UI.escapeHtml(c.value)} (${c.count || 0})</option>`).join('')}
          </select>
          <select id="searchKnowledgeType" class="select select-sm">
            <option value="">全部类型</option>
            ${(filterOptions.knowledge_types || []).map(k => `<option value="${UI.escapeHtml(k.value)}">${UI.escapeHtml(UI.ktypeLabel(k.value))} (${k.count || 0})</option>`).join('')}
          </select>
          <select id="searchTopK" class="select select-sm" data-current-value="3" onchange="SearchPage.handleTopKChange('searchTopK')">
            <option value="3" selected>Top 3</option>
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
            <option value="__custom__">自定义...</option>
          </select>
          <label class="check-control">
            <input type="checkbox" id="searchHighlight" /> 高亮
          </label>
        </div>
      </div>

      <!-- 搜索结果 -->
      <div id="searchResults" style="margin-top: var(--space-6);">
        <div class="empty-state">
          <div class="empty-state-icon">⌕</div>
          <div class="empty-state-title">输入查询开始搜索</div>
          <div class="empty-state-desc">支持自然语言问题，系统将自动改写查询并执行混合检索</div>
        </div>
      </div>
    `);
  }

  async function doSearch() {
    const query = document.getElementById('searchInput')?.value?.trim();
    if (!query) return;

    const topK = readTopK('searchTopK', 3);
    const category = document.getElementById('searchCategory')?.value;
    const knowledgeType = document.getElementById('searchKnowledgeType')?.value;
    const highlight = document.getElementById('searchHighlight')?.checked;

    lastQuery = query;
    document.getElementById('searchResults').innerHTML = `<div class="loading-overlay"><div class="loading-spinner"></div><span>搜索中…</span></div>`;

    try {
      const filters = {};
      if (category) filters.categories = [category];
      if (knowledgeType) filters.knowledge_types = [knowledgeType];
      filters.chunk_status = ['active'];
      filters.index_status = ['indexed'];

      const res = await API.search(query, topK, filters, {
        hybrid: true,
        rewrite: true,
        highlight,
        include_assets: true,
        include_sources: true,
        include_score_components: true,
      });

      const data = res?.data || {};
      lastResult = data;
      renderResults(data, query);
    } catch (e) {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state"><div class="empty-state-icon">⚠</div><div class="empty-state-title">搜索失败</div><div class="empty-state-desc">${UI.escapeHtml(e.message)}</div></div>`;
    }
  }

  function renderResults(data, query) {
    const results = data.results || [];
    const total = data.total_count || results.length;
    const rewritten = data.rewritten_query || '';

    if (results.length === 0) {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🔍</div>
          <div class="empty-state-title">未找到相关结果</div>
          <div class="empty-state-desc">尝试使用不同的关键词或调整过滤条件</div>
        </div>`;
      return;
    }

    const itemsHtml = results.map((item, i) => `
      <div class="result-card" onclick="SearchPage.showResultDetail('${item.chunk_id}')">
        <div class="result-card-header">
          <span class="result-card-title">#${i + 1} ${UI.escapeHtml(item.title || '未命名知识块')}</span>
          <span class="result-card-score">${(item.score || 0).toFixed(4)}</span>
        </div>
        <div class="result-card-content">${UI.escapeHtml((item.content || '').substring(0, 250))}${item.content?.length > 250 ? '…' : ''}</div>
        ${item.highlight ? `<div style="font-size: var(--text-xs); color: var(--celadon-deep); margin-top: var(--space-2);">🔍 ${UI.escapeHtml(item.highlight)}</div>` : ''}
        <div class="result-card-meta">
          ${UI.ktypeBadge(item.knowledge_type)}
          <span class="tag">${UI.escapeHtml(item.category || '')}</span>
          ${item.doc_title ? `<span class="tag">📄 ${UI.escapeHtml(item.doc_title)}</span>` : ''}
          ${item.score_components?.rerank ? `<span class="tag">Rerank: ${item.score_components.rerank.toFixed(4)}</span>` : ''}
        </div>
      </div>
    `).join('');

    document.getElementById('searchResults').innerHTML = `
      <div class="search-stats">
        <span>查询: <strong>${UI.escapeHtml(query)}</strong></span>
        ${rewritten ? `<span>改写: <strong>${UI.escapeHtml(rewritten)}</strong></span>` : ''}
        <span>共 <strong>${total}</strong> 条结果</span>
      </div>
      <div class="result-list">${itemsHtml}</div>
    `;
  }

  function showResultDetail(chunkId) {
    const item = (lastResult?.results || []).find(r => r.chunk_id === chunkId);
    if (!item) return;

    UI.showModal(
      `知识块详情 — ${UI.escapeHtml(item.title || chunkId)}`,
      `
        <div style="font-size: var(--text-sm); line-height: 1.6;">
          <div style="display: flex; gap: var(--space-2); margin-bottom: var(--space-3); flex-wrap: wrap;">
            ${UI.ktypeBadge(item.knowledge_type)}
            <span class="tag">${UI.escapeHtml(item.category || '')}</span>
            <span class="tag">Score: ${(item.score || 0).toFixed(4)}</span>
            ${item.score_components ? `
              <span class="tag">向量: ${item.score_components.vector?.toFixed(4) || '—'}</span>
              <span class="tag">BM25: ${item.score_components.bm25?.toFixed(4) || '—'}</span>
              <span class="tag">Rerank: ${item.score_components.rerank?.toFixed(4) || '—'}</span>
            ` : ''}
          </div>
          <div style="margin-bottom: var(--space-4);">
            <h4>内容</h4>
            <pre class="code-block">${UI.escapeHtml(item.content || '')}</pre>
          </div>
          ${item.doc_title ? `<p><strong>来源文档:</strong> ${UI.escapeHtml(item.doc_title)} (${item.doc_id}) v${item.doc_version || 1}</p>` : ''}
          ${(item.source_refs || []).length ? `
            <div><strong>来源引用:</strong>
              ${item.source_refs.map(ref => `
                <div style="font-size: var(--text-xs); color: var(--ink-wash); padding: var(--space-1) 0;">
                  📄 ${UI.escapeHtml(ref.doc_id || '')} ${ref.source_location?.page != null ? `· 第 ${ref.source_location.page} 页` : ''}
                </div>
              `).join('')}
            </div>` : ''}
        </div>
      `,
      `<button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">关闭</button>`
    );
  }

  /* -----------------------------------------------------------------------
     检索调试（7.6）
     ----------------------------------------------------------------------- */
  async function renderDebug() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '检索调试' }]);
    UI.render(`
      <div class="page-header">
        <h1 class="page-title">检索调试</h1>
        <p class="page-subtitle">查看查询改写、各阶段候选和评分明细</p>
      </div>
      <div class="search-panel kb-query-panel">
        <div class="kb-query-main">
          <div class="search-input-wrap">
            <span class="search-input-icon">⌕</span>
            <input class="input input-lg" type="text" id="debugSearchInput" placeholder="输入查询词，查看各阶段检索链路…"
                   onkeydown="if(event.key==='Enter')SearchPage.doDebugSearch()">
          </div>
          <button class="btn btn-primary" onclick="SearchPage.doDebugSearch()">调试检索</button>
        </div>
        <div class="search-filters kb-filter-bar">
          <select id="debugTopK" class="select select-sm" data-current-value="3" onchange="SearchPage.handleTopKChange('debugTopK')">
            <option value="3" selected>Top 3</option>
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
            <option value="__custom__">自定义...</option>
          </select>
        </div>
      </div>
      <div id="debugResults" style="margin-top: var(--space-4);"></div>
    `);
  }

  async function doDebugSearch() {
    const query = document.getElementById('debugSearchInput')?.value?.trim();
    if (!query) return;
    const topK = readTopK('debugTopK', 3);

    document.getElementById('debugResults').innerHTML = `<div class="loading-overlay"><div class="loading-spinner"></div><span>调试检索中…</span></div>`;

    try {
      const res = await API.searchDebug(query, topK);
      const data = res?.data || {};
      document.getElementById('debugResults').innerHTML = `
        <div class="card" style="margin-bottom: var(--space-4);">
          <h3>查询信息</h3>
          <p>原始查询: <strong>${UI.escapeHtml(data.query || query)}</strong></p>
          <p>改写查询: <strong>${UI.escapeHtml(data.rewritten_query || '(未改写)')}</strong></p>
          <p>过滤条件: <code>${UI.escapeHtml(JSON.stringify(data.filters || {}))}</code></p>
          <p>结果数: <strong>${data.total_count || 0}</strong></p>
        </div>
        <h3>检索结果</h3>
        ${(data.results || []).slice(0, 20).map((r, i) => `
          <div class="debug-item card" style="margin-bottom: var(--space-2); padding: var(--space-3);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <strong>#${i + 1} ${UI.escapeHtml(r.title || r.chunk_id)}</strong>
              <span class="badge">${(r.score || 0).toFixed(4)}</span>
            </div>
            ${r.score_components ? `<div style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: 4px;">
              向量: ${r.score_components.vector?.toFixed(4) || '—'} | BM25: ${r.score_components.bm25?.toFixed(4) || '—'} | Rerank: ${r.score_components.rerank?.toFixed(4) || '—'}
            </div>` : ''}
            <p style="font-size: var(--text-xs); margin-top: 4px;">${UI.escapeHtml((r.content || '').substring(0, 300))}…</p>
          </div>
        `).join('')}
      `;
    } catch (e) {
      document.getElementById('debugResults').innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠</div><div class="empty-state-title">调试失败</div><div class="empty-state-desc">${UI.escapeHtml(e.message)}</div></div>`;
    }
  }

  function readTopK(selectId, fallback) {
    const select = document.getElementById(selectId);
    const raw = select?.value === '__custom__' ? select.dataset.currentValue : select?.value;
    const value = parseInt(raw || `${fallback}`, 10);
    return Number.isFinite(value) ? Math.min(100, Math.max(1, value)) : fallback;
  }

  function handleTopKChange(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return;
    if (select.value !== '__custom__') {
      select.dataset.currentValue = select.value;
      return;
    }
    pendingTopKSelectId = selectId;
    const currentValue = readTopK(selectId, 3);
    select.value = `${currentValue}`;
    showCustomTopKDialog(currentValue);
  }

  function showCustomTopKDialog(currentValue) {
    UI.showModal(
      '自定义 TopK',
      `
        <div class="form-stack">
          <div>
            <label class="field-label">检索数量 <span>*</span></label>
            <input id="customTopKInput" class="input input-number" type="number" min="1" max="100" step="1"
                   value="${currentValue}" style="width: 100%; text-align: left;"
                   onkeydown="if(event.key==='Enter')SearchPage.confirmCustomTopK();if(event.key==='Escape')SearchPage.cancelCustomTopK();">
            <div class="field-help">请输入 1 到 100 之间的整数。</div>
            <div id="customTopKError" class="field-warning is-hidden">请输入 1 到 100 之间的整数。</div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="SearchPage.cancelCustomTopK()">取消</button>
        <button class="btn btn-primary" onclick="SearchPage.confirmCustomTopK()">确认</button>
      `
    );
    setTimeout(() => document.getElementById('customTopKInput')?.focus(), 50);
  }

  function cancelCustomTopK() {
    const select = document.getElementById(pendingTopKSelectId);
    if (select) select.value = select.dataset.currentValue || '3';
    document.querySelector('.modal-backdrop:last-child')?.remove();
    pendingTopKSelectId = '';
  }

  function confirmCustomTopK() {
    const input = document.getElementById('customTopKInput');
    const error = document.getElementById('customTopKError');
    const value = parseInt(input?.value || '', 10);
    if (!Number.isFinite(value) || value < 1 || value > 100) {
      if (error) error.classList.remove('is-hidden');
      input?.focus();
      return;
    }

    const select = document.getElementById(pendingTopKSelectId);
    if (select) {
      upsertCustomTopKOption(select, value);
      select.value = `${value}`;
      select.dataset.currentValue = `${value}`;
    }
    document.querySelector('.modal-backdrop:last-child')?.remove();
    pendingTopKSelectId = '';
  }

  function upsertCustomTopKOption(select, value) {
    const customOption = select.querySelector('option[data-custom-topk="true"]');
    const presetOption = [...select.options].find((option) =>
      option.value === `${value}` && option.dataset.customTopk !== 'true'
    );
    if (presetOption) {
      customOption?.remove();
      return;
    }
    if (customOption) {
      customOption.value = `${value}`;
      customOption.textContent = `Top ${value}（自定义）`;
      return;
    }
    const option = document.createElement('option');
    option.value = `${value}`;
    option.textContent = `Top ${value}（自定义）`;
    option.dataset.customTopk = 'true';
    select.insertBefore(option, select.querySelector('option[value="__custom__"]'));
  }

  return {
    render, doSearch, showResultDetail, renderDebug, doDebugSearch,
    handleTopKChange, cancelCustomTopK, confirmCustomTopK,
  };
})();
