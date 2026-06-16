/* ==========================================================================
   搜索页面组件 — 混合检索的核心交互界面（签名元素）
   展示向量 + BM25 + RRF 融合的检索来源指示器
   ========================================================================== */

const SearchPage = (() => {

  let lastResult = null;
  let lastQuery = '';

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '知识搜索' }]);

    UI.render(`
      <div class="search-hero">
        <h1 class="page-title" style="margin-bottom: var(--space-6);">知识搜索</h1>

        <!-- 搜索框 — 核心交互 -->
        <div class="search-input-wrap">
          <span class="search-input-icon">⌕</span>
          <input class="input input-lg"
                 type="text"
                 id="searchInput"
                 placeholder="输入您的问题，系统将使用混合检索查找最相关的知识块…"
                 autofocus
                 onkeydown="if(event.key==='Enter')SearchPage.doSearch()">
        </div>

        <!-- 搜索过滤器 -->
        <div class="search-filters">
          <span style="font-size: var(--text-xs); color: var(--ink-wash);">检索数量:</span>
          <select class="select" id="topKSelect">
            <option value="5" selected>Top 5</option>
            <option value="10">Top 10</option>
            <option value="20">Top 20</option>
          </select>

          <span style="font-size: var(--text-xs); color: var(--ink-wash); margin-left: var(--space-2);">分类:</span>
          <select class="select" id="categoryFilter">
            <option value="">全部</option>
            <option value="通用">通用</option>
            <option value="技术">技术</option>
            <option value="产品">产品</option>
            <option value="业务">业务</option>
          </select>

          <button class="btn btn-primary" onclick="SearchPage.doSearch()" style="margin-left: var(--space-2);">
            ⌕ 搜索
          </button>
        </div>

        <!-- 检索模式说明 -->
        <div style="display: flex; gap: var(--space-4); margin-top: var(--space-4); flex-wrap: wrap;">
          <div style="display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-xs); color: var(--ink-wash);">
            <span class="provenance-vector">向量</span> 语义相似度匹配
          </div>
          <div style="display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-xs); color: var(--ink-wash);">
            <span class="provenance-bm25">BM25</span> 关键词全文检索
          </div>
          <div style="display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-xs); color: var(--ink-wash);">
            <span class="provenance-both">融合</span> RRF + LLM 重排序
          </div>
        </div>
      </div>

      <!-- 搜索结果区域 -->
      <div id="searchResults">
        <div class="empty-state">
          <div class="empty-state-icon">⌕</div>
          <div class="empty-state-title">输入查询开始搜索</div>
          <div class="empty-state-desc">
            系统将自动进行查询改写，并使用向量检索 + BM25 全文检索双路召回，经 RRF 融合后由 LLM 重排序，返回最相关的知识块。
          </div>
        </div>
      </div>
    `);

    // 聚焦搜索框
    setTimeout(() => document.getElementById('searchInput')?.focus(), 100);
  }

  async function doSearch() {
    const input = document.getElementById('searchInput');
    const query = input?.value?.trim();
    if (!query) {
      UI.toast('请输入搜索内容', 'info');
      return;
    }

    const topK = parseInt(document.getElementById('topKSelect')?.value || '5');
    const category = document.getElementById('categoryFilter')?.value || '';

    const filters = {};
    if (category) filters.category = category;

    lastQuery = query;

    // 显示加载状态
    document.getElementById('searchResults').innerHTML = `
      <div class="loading-overlay">
        <div class="loading-spinner"></div>
        <span>正在检索…</span>
      </div>
    `;

    try {
      lastResult = await API.search(query, topK, filters);
      renderResults();
    } catch (e) {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">⚠</div>
          <div class="empty-state-title">搜索失败</div>
          <div class="empty-state-desc">${UI.escapeHtml(e.message)}</div>
          <button class="btn btn-secondary" onclick="SearchPage.doSearch()" style="margin-top: var(--space-4);">⟳ 重试</button>
        </div>
      `;
    }
  }

  function renderResults() {
    const result = lastResult;
    const items = result?.results || [];
    const total = result?.total_count ?? items.length;
    const rewritten = result?.rewritten_query;
    const searchId = result?.search_id;

    let resultsHtml = '';

    if (items.length === 0) {
      resultsHtml = `
        <div class="empty-state">
          <div class="empty-state-icon">∅</div>
          <div class="empty-state-title">未找到相关结果</div>
          <div class="empty-state-desc">尝试使用不同的关键词，或调整搜索过滤条件。</div>
        </div>`;
    } else {
      resultsHtml = items.map((item, i) => renderResultItem(item, i)).join('');
    }

    document.getElementById('searchResults').innerHTML = `
      <div class="search-stats">
        ${rewritten && rewritten !== lastQuery ? `
          <div class="rewritten-query" style="margin-bottom: var(--space-3); display: flex; align-items: center; gap: var(--space-2);">
            查询改写: <span class="rewritten-query-text">${UI.escapeHtml(rewritten)}</span>
          </div>` : ''}
        <span>找到 <strong>${total}</strong> 条结果</span>
        ${searchId ? `<span style="color: var(--ink-wash-light);">· 搜索ID: ${UI.escapeHtml(searchId.slice(0, 12))}…</span>` : ''}
      </div>
      <div class="result-list">
        ${resultsHtml}
      </div>
    `;
  }

  /**
   * 渲染单个搜索结果 — 包含检索来源指示器（签名元素）
   */
  function renderResultItem(item, index) {
    const score = item.score != null ? item.score.toFixed(4) : '—';
    const sc = item.score_components || {};

    return `
      <div class="result-card" onclick="SearchPage.showResultDetail('${UI.escapeHtml(item.chunk_id || '')}')">
        <div class="result-card-header">
          <div class="result-card-title">${UI.escapeHtml(item.title || '未命名知识块')}</div>
          <div class="result-card-score">${score}</div>
        </div>
        <div class="result-card-content">${UI.escapeHtml(item.content || '')}</div>
        <div class="result-card-meta">
          ${item.knowledge_type ? UI.ktypeBadge(item.knowledge_type) : ''}
          ${item.category ? `<span class="badge badge-neutral">${UI.escapeHtml(item.category)}</span>` : ''}

          <!-- 检索来源指示器 -->
          ${renderProvenance(sc)}

          ${item.source_refs?.length ? `<span class="tag">📎 ${item.source_refs.length} 个来源</span>` : ''}
          ${item.asset_refs?.length ? `<span class="tag">🖼 ${item.asset_refs.length} 个资源</span>` : ''}
        </div>

        <!-- 分数分解 -->
        ${(sc.vector != null || sc.bm25 != null || sc.rerank != null) ? `
        <div class="score-breakdown">
          ${sc.vector != null ? `
          <div class="score-component">
            <span class="score-component-label">向量</span>
            <span class="score-component-value">${sc.vector.toFixed(3)}</span>
            <div class="score-component-bar"><div class="score-component-bar-fill vector" style="width: ${Math.min(sc.vector * 100, 100)}%;"></div></div>
          </div>` : ''}
          ${sc.bm25 != null ? `
          <div class="score-component">
            <span class="score-component-label">BM25</span>
            <span class="score-component-value">${sc.bm25.toFixed(3)}</span>
            <div class="score-component-bar"><div class="score-component-bar-fill bm25" style="width: ${Math.min(sc.bm25 * 100, 100)}%;"></div></div>
          </div>` : ''}
          ${sc.rerank != null ? `
          <div class="score-component">
            <span class="score-component-label">重排序</span>
            <span class="score-component-value">${sc.rerank.toFixed(3)}</span>
            <div class="score-component-bar"><div class="score-component-bar-fill rerank" style="width: ${Math.min(sc.rerank * 100, 100)}%;"></div></div>
          </div>` : ''}
        </div>` : ''}
      </div>
    `;
  }

  /**
   * 检索来源指示器 — 判断命中了哪些检索路径
   */
  function renderProvenance(sc) {
    if (!sc) return '';
    const hasVector = sc.vector != null && sc.vector > 0;
    const hasBM25 = sc.bm25 != null && sc.bm25 > 0;

    if (hasVector && hasBM25) {
      return `<span class="provenance-indicator provenance-both" title="向量 + BM25 双路命中">⚡ 双路命中</span>`;
    } else if (hasVector) {
      return `<span class="provenance-indicator provenance-vector" title="向量语义匹配命中">⊡ 语义匹配</span>`;
    } else if (hasBM25) {
      return `<span class="provenance-indicator provenance-bm25" title="BM25 关键词匹配命中">≡ 关键词命中</span>`;
    }
    return '';
  }

  function showResultDetail(chunkId) {
    if (!chunkId) return;
    // 展示知识块完整内容（模态框）
    const item = lastResult?.results?.find(r => r.chunk_id === chunkId);
    if (!item) return;

    const sc = item.score_components || {};
    const scoreDetails = [
      sc.vector != null ? `向量: ${sc.vector.toFixed(4)}` : '',
      sc.bm25 != null ? `BM25: ${sc.bm25.toFixed(4)}` : '',
      sc.rerank != null ? `重排序: ${sc.rerank.toFixed(4)}` : '',
    ].filter(Boolean).join(' · ');

    UI.showModal(
      item.title || '知识块详情',
      `
        <div style="margin-bottom: var(--space-4);">
          <div style="display: flex; gap: var(--space-2); margin-bottom: var(--space-3); flex-wrap: wrap;">
            ${item.knowledge_type ? UI.ktypeBadge(item.knowledge_type) : ''}
            ${item.category ? `<span class="badge badge-neutral">${UI.escapeHtml(item.category)}</span>` : ''}
            <span class="badge badge-info">得分: ${item.score?.toFixed(4) || '—'}</span>
          </div>
          ${scoreDetails ? `<p style="font-size: var(--text-xs); color: var(--ink-wash); margin-bottom: var(--space-3);">${scoreDetails}</p>` : ''}
        </div>
        <div style="background: var(--silk); border-radius: var(--radius-md); padding: var(--space-5); line-height: 1.8; font-size: var(--text-sm); white-space: pre-wrap; max-height: 400px; overflow-y: auto;">
          ${UI.escapeHtml(item.content || '(无内容)')}
        </div>
        ${item.source_refs?.length ? `
          <div style="margin-top: var(--space-4);">
            <h4 style="font-size: var(--text-xs); color: var(--ink-wash); margin-bottom: var(--space-2);">来源引用</h4>
            ${item.source_refs.map(ref => `
              <div style="font-size: var(--text-xs); color: var(--ink-wash); padding: var(--space-1) 0;">
                📄 ${UI.escapeHtml(ref.doc_id || '')}
                ${ref.source_location?.page != null ? ` · 第 ${ref.source_location.page} 页` : ''}
                ${ref.source_location?.section_path?.length ? ` · ${ref.source_location.section_path.join(' > ')}` : ''}
              </div>
            `).join('')}
          </div>` : ''}
      `,
      `<button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">关闭</button>`
    );
  }

  return { render, doSearch, showResultDetail };
})();
