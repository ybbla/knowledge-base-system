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
        <p class="page-subtitle">按问题检索知识块，支持分类和知识类型过滤</p>
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
        highlight: true,
        include_assets: true,
        include_sources: true,
        include_score_components: true,
      });

      const data = res?.data || {};
      lastResult = data;
      renderResults(data, query);
    } catch (e) {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state empty-state-error"><div class="empty-state-icon">!</div><div class="empty-state-title">搜索失败</div><div class="empty-state-desc">${UI.escapeHtml(e.message)}</div></div>`;
    }
  }

  function buildSearchFilters({ category, knowledgeType }) {
    const filters = { chunk_status: ['active'], index_status: ['indexed'] };
    if (category) filters.categories = [category];
    if (knowledgeType) filters.knowledge_types = [knowledgeType];
    return filters;
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
          ${item.doc_title ? `<span class="tag">来源：${UI.escapeHtml(item.doc_title)}</span>` : ''}
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
     检索调试 — 全链路追踪
     ----------------------------------------------------------------------- */

  // 生成候选列表 HTML
  function renderCandidateList(candidates, title, count, maxShow = 10, scoreLabel = '分数') {
    if (!candidates || candidates.length === 0) {
      return `<p style="color: var(--ink-wash); font-size: var(--text-sm);">无候选结果</p>`;
    }
    const showList = candidates.slice(0, maxShow);
    return `
      <h4>${title} <span class="badge badge-sm">${count || candidates.length} 条</span></h4>
      <div class="debug-candidate-list">
        ${showList.map((c, i) => `
          <div class="debug-candidate-item">
            <span class="debug-rank">#${i + 1}</span>
            <span class="debug-candidate-title" title="${UI.escapeHtml(c.chunk_id || '')}">${UI.escapeHtml(c.title || c.chunk_id || '未命名')}</span>
            <span class="debug-score">${(c.score || 0).toFixed(4)}</span>
          </div>
        `).join('')}
        ${candidates.length > maxShow ? `<p style="font-size: var(--text-xs); color: var(--ink-wash); margin: var(--space-2) 0 0 var(--space-6);">还有 ${candidates.length - maxShow} 条未显示</p>` : ''}
      </div>
    `;
  }

  // 生成最终结果 HTML
  function renderFinalResults(results) {
    if (!results || results.length === 0) {
      return `<p style="color: var(--ink-wash); font-size: var(--text-sm);">无最终结果</p>`;
    }
    return results.map((r, i) => `
      <div class="debug-result-item">
        <div class="debug-result-header">
          <span class="debug-rank">#${i + 1}</span>
          <span class="debug-result-title" title="${UI.escapeHtml(r.chunk_id || '')}">${UI.escapeHtml(r.title || r.chunk_id || '未命名')}</span>
          <span class="debug-score">${(r.score || 0).toFixed(4)}</span>
        </div>
        ${r.score_components ? `<div class="debug-score-components">
          <span class="score-badge score-badge-vector">向量 ${r.score_components.vector?.toFixed(4) || '—'}</span>
          <span class="score-badge score-badge-bm25">BM25 ${r.score_components.bm25?.toFixed(4) || '—'}</span>
          <span class="score-badge score-badge-rerank">Rerank ${r.score_components.rerank?.toFixed(4) || '—'}</span>
        </div>` : ''}
        <p class="debug-result-content">${UI.escapeHtml((r.content || '').substring(0, 200))}${r.content?.length > 200 ? '…' : ''}</p>
      </div>
    `).join('');
  }

  async function renderDebug() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '检索调试' }]);
    let filterOptions = {};
    try {
      const res = await API.searchFilters();
      filterOptions = res?.data || {};
    } catch (e) { /* ignore */ }

    UI.render(`
      <style>
        .debug-section {
          background: var(--bg-surface);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-md);
          padding: var(--space-4);
          margin-bottom: var(--space-4);
        }
        .debug-section h4 {
          margin: 0 0 var(--space-3) 0;
          font-size: var(--text-md);
          color: var(--ink-main);
        }
        .debug-flow-arrow {
          text-align: center;
          font-size: 24px;
          color: var(--celadon-deep);
          margin: var(--space-2) 0;
        }
        .debug-candidate-list {
          display: flex;
          flex-direction: column;
          gap: var(--space-1);
        }
        .debug-candidate-item {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          padding: var(--space-2);
          background: var(--bg-inset);
          border-radius: var(--radius-sm);
          font-size: var(--text-sm);
        }
        .debug-rank {
          min-width: 30px;
          color: var(--celadon-deep);
          font-weight: 600;
          font-family: var(--font-mono);
        }
        .debug-candidate-title {
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .debug-score {
          font-family: var(--font-mono);
          font-size: var(--text-xs);
          color: var(--ink-wash);
          background: var(--bg-inset);
          padding: 2px 6px;
          border-radius: var(--radius-sm);
        }
        .debug-result-item {
          background: var(--bg-inset);
          border-radius: var(--radius-md);
          padding: var(--space-3);
          margin-bottom: var(--space-2);
        }
        .debug-result-header {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          margin-bottom: var(--space-2);
        }
        .debug-result-title {
          flex: 1;
          font-weight: 600;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .debug-score-components {
          display: flex;
          gap: var(--space-2);
          margin-bottom: var(--space-2);
        }
        .score-badge {
          font-size: var(--text-xs);
          font-family: var(--font-mono);
          padding: 2px 8px;
          border-radius: var(--radius-sm);
        }
        .score-badge-vector { background: #dbeafe; color: #1e40af; }
        .score-badge-bm25 { background: #dcfce7; color: #166534; }
        .score-badge-rerank { background: #f3e8ff; color: #6b21a8; }
        .debug-result-content {
          margin: 0;
          font-size: var(--text-sm);
          color: var(--ink-wash);
          line-height: 1.5;
        }
        .rewrite-box {
          display: grid;
          grid-template-columns: 1fr 20px 1fr;
          gap: var(--space-3);
          align-items: center;
        }
        .rewrite-arrow {
          text-align: center;
          color: var(--celadon-deep);
          font-size: 18px;
        }
        .keywords-list {
          display: flex;
          flex-wrap: wrap;
          gap: var(--space-1);
          margin-top: var(--space-2);
        }
        .keyword-tag {
          background: var(--celadon-light);
          color: var(--celadon-deep);
          padding: 2px 8px;
          border-radius: var(--radius-sm);
          font-size: var(--text-xs);
        }
        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: var(--space-2);
        }
        .stat-item {
          text-align: center;
          padding: var(--space-2);
          background: var(--bg-inset);
          border-radius: var(--radius-md);
        }
        .stat-value {
          font-size: var(--text-xl);
          font-weight: 600;
          font-family: var(--font-mono);
          color: var(--celadon-deep);
        }
        .stat-label {
          font-size: var(--text-xs);
          color: var(--ink-wash);
          margin-top: 2px;
        }
      </style>

      <div class="page-header">
        <h1 class="page-title">检索调试</h1>
        <p class="page-subtitle">查看查询改写、各阶段候选和评分明细，追踪完整检索链路</p>
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
          <select id="debugCategory" class="select select-sm">
            <option value="">全部分类</option>
            ${(filterOptions.categories || []).map(c => `<option value="${UI.escapeHtml(c.value)}">${UI.escapeHtml(c.value)} (${c.count || 0})</option>`).join('')}
          </select>
          <select id="debugKnowledgeType" class="select select-sm">
            <option value="">全部类型</option>
            ${(filterOptions.knowledge_types || []).map(k => `<option value="${UI.escapeHtml(k.value)}">${UI.escapeHtml(UI.ktypeLabel(k.value))} (${k.count || 0})</option>`).join('')}
          </select>
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
      <div id="debugEmptyState" class="empty-state">
        <div class="empty-state-icon">⌕</div>
        <div class="empty-state-title">输入查询查看检索链路</div>
        <div class="empty-state-desc">调试页用于排查召回、融合和重排效果，普通检索请使用知识搜索页面。</div>
      </div>
    `);
  }

  async function doDebugSearch() {
    const query = document.getElementById('debugSearchInput')?.value?.trim();
    if (!query) return;
    const topK = readTopK('debugTopK', 3);
    const filters = buildSearchFilters({
      category: document.getElementById('debugCategory')?.value,
      knowledgeType: document.getElementById('debugKnowledgeType')?.value,
    });

    document.getElementById('debugEmptyState')?.remove();
    document.getElementById('debugResults').innerHTML = `<div class="loading-overlay"><div class="loading-spinner"></div><span>调试检索中…</span></div>`;

    try {
      const res = await API.searchDebug(query, topK, filters);
      const data = res?.data || {};
      const stats = data.stats || {};

      document.getElementById('debugResults').innerHTML = `
        <!-- 1. 统计概览 -->
        <div class="debug-section">
          <h4>📊 检索统计</h4>
          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-value">${stats.vector_count || 0}</div>
              <div class="stat-label">向量召回</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">${stats.bm25_count || 0}</div>
              <div class="stat-label">BM25 召回</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">${stats.fused_count || 0}</div>
              <div class="stat-label">融合候选</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">${data.total_count || 0}</div>
              <div class="stat-label">最终结果</div>
            </div>
          </div>
          ${stats.used_milvus_hybrid ? `<p style="margin-top: var(--space-3); font-size: var(--text-sm); color: var(--celadon-deep);">✅ 使用 Milvus Hybrid Search</p>` : ''}
          ${(data.errors || []).length > 0 ? `
            <div style="margin-top: var(--space-3); padding: var(--space-2); background: #fef2f2; border-radius: var(--radius-md);">
              <p style="color: #991b1b; font-size: var(--text-sm); margin: 0;">⚠️ 警告</p>
              <ul style="margin: var(--space-1) 0 0 var(--space-4); padding: 0; color: #991b1b; font-size: var(--text-xs);">
                ${(data.errors || []).map(e => `<li>${UI.escapeHtml(e)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
        </div>

        <!-- 2. 查询改写 -->
        <div class="debug-section">
          <h4>📝 查询改写</h4>
          <div class="rewrite-box">
            <div>
              <p style="font-size: var(--text-xs); color: var(--ink-wash); margin: 0 0 4px 0;">原始查询</p>
              <p style="font-size: var(--text-md); font-weight: 600; margin: 0;">${UI.escapeHtml(data.query || query)}</p>
            </div>
            <div class="rewrite-arrow">→</div>
            <div>
              <p style="font-size: var(--text-xs); color: var(--ink-wash); margin: 0 0 4px 0;">改写后查询</p>
              <p style="font-size: var(--text-md); font-weight: 600; margin: 0; color: var(--celadon-deep);">${UI.escapeHtml(data.rewritten_query || '(未改写)')}</p>
            </div>
          </div>
          ${data.keywords && data.keywords.length > 0 ? `
            <div class="keywords-list">
              ${data.keywords.map(k => `<span class="keyword-tag">${UI.escapeHtml(k)}</span>`).join('')}
            </div>
          ` : ''}
        </div>

        <div class="debug-flow-arrow">↓</div>

        <!-- 3. 向量检索 -->
        <div class="debug-section">
          ${renderCandidateList(data.vector_candidates, '🎯 向量检索 (Embedding)', stats.vector_count)}
        </div>

        <div class="debug-flow-arrow">↓</div>

        <!-- 4. BM25 检索 -->
        <div class="debug-section">
          ${renderCandidateList(data.bm25_candidates, '🔍 BM25 关键词检索', stats.bm25_count)}
        </div>

        <div class="debug-flow-arrow">↘ ↙</div>

        <!-- 5. RRF 融合 -->
        <div class="debug-section">
          ${renderCandidateList(data.fused_candidates, '🔗 RRF 分数融合', stats.fused_count)}
        </div>

        <div class="debug-flow-arrow">↓</div>

        <!-- 6. LLM Rerank -->
        <div class="debug-section">
          ${renderCandidateList(data.rerank_results, '🤖 LLM 重排 (Rerank)', stats.rerank_count, 10, 'Relevance')}
        </div>

        <div class="debug-flow-arrow">↓</div>

        <!-- 7. 最终结果（过滤后） -->
        <div class="debug-section">
          <h4>📋 最终结果（过滤后） <span class="badge badge-sm">${data.total_count || 0} 条</span></h4>
          ${renderFinalResults(data.results || [])}
        </div>
      `;
    } catch (e) {
      document.getElementById('debugResults').innerHTML = `<div class="empty-state empty-state-error"><div class="empty-state-icon">!</div><div class="empty-state-title">调试失败</div><div class="empty-state-desc">${UI.escapeHtml(e.message)}</div></div>`;
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
    showCustomTopKDialog();
  }

  function showCustomTopKDialog() {
    UI.showModal(
      '自定义 TopK',
      `
        <div class="form-stack">
          <div>
            <label class="field-label">检索数量 <span>*</span></label>
            <input id="customTopKInput" class="input input-number" type="number" min="1" max="100" step="1"
                   value="" placeholder="请输入检索数量" style="width: 100%; text-align: left;"
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
