/* ==========================================================================
   Chunks — 知识块管理页面（v1 API）

   功能：筛选、分页列表、详情抽屉、编辑、删除、恢复、重建索引
   样式：与仪表盘设计令牌一致（绢本 Silk Scroll）
   ========================================================================== */

const Chunks = (() => {

  let currentPage = 1;
  let selectedIds = new Set();
  let filterOptions = {};  // 从后端动态加载的筛选项
  let previousCreateDocCategory = '通用';

  /* -----------------------------------------------------------------------
     Render — 渲染主容器
     ----------------------------------------------------------------------- */
  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '知识块管理' }]);

    // 动态加载筛选项：分类、类型、状态、索引状态
    try {
      const res = await API.searchFilters();
      filterOptions = res?.data || {};
    } catch (e) { filterOptions = {}; }

    // 加载文档列表用于文档筛选
    let docOptions = [];
    try {
      const docsRes = await API.listDocuments({ page_size: 200, status: 'active' });
      docOptions = docsRes?.data || [];
    } catch (e) { docOptions = []; }

    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">知识块管理</h1>
            <p class="page-subtitle">浏览和管理所有已抽取的知识块，支持筛选、编辑、重建索引</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline btn-sm" onclick="Chunks.batchReindex()" id="batchReindexChunkBtn" disabled>批量重建索引</button>
            <button class="btn btn-outline btn-sm" onclick="Chunks.batchDelete()" id="batchDeleteChunkBtn" disabled>批量删除</button>
            <button class="btn btn-primary" onclick="Chunks.showCreateDialog()">+ 新建知识块</button>
          </div>
        </div>
      </div>

      <!-- 筛选工具栏 -->
      <div class="doc-toolbar kb-filter-bar chunk-filter-bar">
        <input class="input kb-toolbar-search" type="text" id="chunkKeyword" placeholder="搜索标题 / 内容…"
               onkeydown="if(event.key==='Enter')Chunks.load()">
        <select class="select select-sm" id="chunkDocFilter" onchange="Chunks.load()">
          <option value="">全部文档</option>
          ${docOptions.map(d => `<option value="${UI.escapeHtml(d.doc_id)}">${UI.escapeHtml(d.title || d.doc_id)}</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkIndexFilter" onchange="Chunks.load()">
          <option value="">全部索引状态</option>
          ${(filterOptions.index_statuses || []).map(s => `<option value="${UI.escapeHtml(s.value)}">${indexStatusLabel(s.value)} (${s.count || 0})</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkStatusFilter" onchange="Chunks.load()">
          <option value="">全部状态</option>
          ${(filterOptions.chunk_statuses || []).map(s => `<option value="${UI.escapeHtml(s.value)}">${chunkStatusLabel(s.value)} (${s.count || 0})</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkCategoryFilter" onchange="Chunks.load()">
          <option value="">全部分类</option>
          ${(filterOptions.categories || []).map(c => `<option value="${UI.escapeHtml(c.value)}">${UI.escapeHtml(c.value)} (${c.count || 0})</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkTypeFilter" onchange="Chunks.load()">
          <option value="">全部类型</option>
          ${(filterOptions.knowledge_types || []).map(k => `<option value="${UI.escapeHtml(k.value)}">${UI.ktypeLabel(k.value)} (${k.count || 0})</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkSortFilter" onchange="Chunks.load()">
          <option value="chunk_id:desc">最近写入</option>
          <option value="indexed_at:desc">最近索引</option>
          <option value="title:asc">标题 A-Z</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="Chunks.resetFilters()">清空筛选</button>
        <span class="doc-count" id="chunkCountText">—</span>
      </div>

      <!-- 表格 -->
      <div class="table-wrap">
        <table class="chunk-table">
          <thead>
            <tr>
              <th style="width: 3%;"><input type="checkbox" id="chunkSelectAll" onclick="Chunks.toggleSelectAll()" /></th>
              <th style="width: 27%;">知识内容</th>
              <th style="width: 14%;">来源文档</th>
              <th style="width: 9%;">分类</th>
              <th style="width: 8%;">类型</th>
              <th style="width: 8%;">状态</th>
              <th style="width: 11%;">索引</th>
              <th style="width: 9%;">索引时间</th>
              <th style="width: 11%;">操作</th>
            </tr>
          </thead>
          <tbody id="chunkTableBody">
            <tr><td colspan="9"><div class="loading-overlay"><div class="loading-spinner"></div><span>加载知识块…</span></div></td></tr>
          </tbody>
        </table>
      </div>

      <div id="chunkPagination" class="pagination"></div>

      <!-- 详情抽屉 -->
      <div id="chunkDetailDrawer" class="drawer" style="display:none">
        <div class="drawer-overlay" onclick="Chunks.closeDrawer()"></div>
        <div class="drawer-content">
          <div class="drawer-header">
            <h2 id="chunkDetailTitle">知识块详情</h2>
            <button class="btn-close" onclick="Chunks.closeDrawer()">&times;</button>
          </div>
          <div id="chunkDetailBody" class="drawer-body"></div>
        </div>
      </div>
    `);

    await load();
  }

  /* -----------------------------------------------------------------------
     Load — 加载知识块列表
     ----------------------------------------------------------------------- */
  async function load(page = 1) {
    currentPage = page;
    renderLoading();
    const keyword = document.getElementById('chunkKeyword')?.value?.trim() || '';
    const docId = document.getElementById('chunkDocFilter')?.value || '';
    const knowledgeType = document.getElementById('chunkTypeFilter')?.value || '';
    const category = document.getElementById('chunkCategoryFilter')?.value || '';
    const status = document.getElementById('chunkStatusFilter')?.value || '';
    const indexStatus = document.getElementById('chunkIndexFilter')?.value || '';
    const [sortBy, sortOrder] = (document.getElementById('chunkSortFilter')?.value || 'chunk_id:desc').split(':');

    try {
      const res = await API.listChunks({
        page, page_size: 20,
        keyword: keyword || undefined,
        doc_id: docId || undefined,
        category: category || undefined,
        knowledge_type: knowledgeType || undefined,
        status: status || undefined,
        index_status: indexStatus || undefined,
        sort_by: sortBy || 'chunk_id',
        sort_order: sortOrder || 'desc',
      });
      renderTable(res);
    } catch (e) {
      renderError(e.message || '请求失败');
      UI.toast(`加载知识块失败：${e.message}`, 'error');
    }
  }

  function renderLoading() {
    const tbody = document.getElementById('chunkTableBody');
    const pagEl = document.getElementById('chunkPagination');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="loading-overlay"><div class="loading-spinner"></div><span>加载知识块...</span></div></td></tr>`;
    }
    if (pagEl) pagEl.innerHTML = '';
  }

  function renderError(message) {
    const tbody = document.getElementById('chunkTableBody');
    const pagEl = document.getElementById('chunkPagination');
    if (tbody) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="9">
        <div class="empty-state empty-state-error">
          <div class="empty-state-icon">!</div>
          <div class="empty-state-title">知识块加载失败</div>
          <div class="empty-state-desc">${UI.escapeHtml(message)}</div>
          <div class="empty-actions">
            <button class="btn btn-primary" onclick="Chunks.load(${currentPage})">重新加载</button>
          </div>
        </div>
      </td></tr>`;
    }
    if (pagEl) pagEl.innerHTML = '';
  }

  function renderTable(res) {
    selectedIds.clear();
    const tbody = document.getElementById('chunkTableBody');
    const data = res?.data || [];
    const meta = res?.meta || {};
    const total = meta.total || 0;
    const countEl = document.getElementById('chunkCountText');
    if (countEl) countEl.textContent = `共 ${total} 个知识块`;

    if (!data.length) {
      const hasFilters = hasActiveFilters();
      tbody.innerHTML = `<tr class="empty-row"><td colspan="9">
        <div class="empty-state">
          <div class="empty-state-icon">⊞</div>
          <div class="empty-state-title">${hasFilters ? '未找到匹配知识块' : '暂无知识块'}</div>
          <div class="empty-state-desc">${hasFilters ? '当前筛选条件下没有知识块。可以调整关键词、文档、类型或索引状态后再试。' : '上传文档并完成入库后，知识块将自动出现在这里。'}</div>
          <div class="empty-actions">
            ${hasFilters ? '<button class="btn btn-secondary" onclick="Chunks.resetFilters()">清空筛选</button>' : ''}
            <button class="btn btn-primary" onclick="Documents.showUploadModal()">上传文档</button>
          </div>
        </div>
      </td></tr>`;
    } else {
      tbody.innerHTML = data.map(c => `
        <tr>
          <td><input type="checkbox" value="${c.chunk_id}" class="chunk-checkbox" onclick="Chunks.toggleSelect(event)" /></td>
          <td>
            <div class="chunk-title-cell">
              <span class="doc-title-link" onclick="Chunks.showDetail('${c.chunk_id}')">${UI.escapeHtml(c.title || '(无标题)')}</span>
              <span class="chunk-preview">${UI.escapeHtml((c.content_preview || c.content || '').substring(0, 96))}${(c.content_preview || c.content || '').length > 96 ? '…' : ''}</span>
              ${renderChunkMiniMeta(c)}
            </div>
          </td>
          <td>${UI.escapeHtml(c.doc_title || c.doc_id || '—')}</td>
          <td>${UI.escapeHtml(c.category || '通用')}</td>
          <td>${UI.ktypeBadge(c.knowledge_type)}</td>
          <td>${UI.statusBadge(c.status || 'active')}</td>
          <td>
            <div class="index-cell">
              ${UI.statusBadge(c.index_status || 'pending')}
              ${c.index_error ? `<span class="index-error">${UI.escapeHtml(c.index_error)}</span>` : ''}
            </div>
          </td>
          <td>${UI.formatTime(c.indexed_at)}</td>
          <td class="actions-cell">
            <button class="btn btn-sm btn-ghost" onclick="Chunks.showDetail('${c.chunk_id}')">详情</button>
            ${c.status === 'deleted'
              ? `<button class="btn btn-sm btn-success" onclick="Chunks.restoreChunk('${c.chunk_id}')">恢复</button>`
              : `
                <button class="btn btn-sm btn-ghost" onclick="Chunks.reindexChunk('${c.chunk_id}')">重建索引</button>
                <button class="btn btn-sm btn-danger" onclick="Chunks.deleteChunk('${c.chunk_id}')">删除</button>
              `}
          </td>
        </tr>
      `).join('');
    }

    // 分页
    const pagEl = document.getElementById('chunkPagination');
    const totalPages = meta.total_pages || 1;
    if (totalPages > 1) {
      pagEl.innerHTML = `
        <button class="btn btn-sm btn-secondary" onclick="Chunks.load(${Math.max(1, currentPage - 1)})" ${currentPage <= 1 ? 'disabled' : ''}>‹ 上一页</button>
        <span class="pagination-info">${currentPage} / ${totalPages}（共 ${total} 条）</span>
        <button class="btn btn-sm btn-secondary" onclick="Chunks.load(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一页 ›</button>`;
    } else {
      pagEl.innerHTML = total > 0 ? `<span class="pagination-info">共 ${total} 条</span>` : '';
    }
    updateBatchBtn();
  }

  function renderChunkMiniMeta(chunk) {
    const parts = [];
    if ((chunk.asset_count || 0) > 0) parts.push(`${chunk.asset_count} 资源`);
    if ((chunk.source_count || 0) > 0) parts.push(`${chunk.source_count} 来源`);
    if (!parts.length) return '';
    return `<span class="chunk-mini-meta">${parts.map(UI.escapeHtml).join(' / ')}</span>`;
  }

  function hasActiveFilters() {
    return Boolean(
      document.getElementById('chunkKeyword')?.value?.trim()
      || document.getElementById('chunkDocFilter')?.value
      || document.getElementById('chunkTypeFilter')?.value
      || document.getElementById('chunkCategoryFilter')?.value
      || document.getElementById('chunkStatusFilter')?.value
      || document.getElementById('chunkIndexFilter')?.value
    );
  }

  function resetFilters() {
    ['chunkKeyword', 'chunkDocFilter', 'chunkTypeFilter', 'chunkCategoryFilter', 'chunkStatusFilter', 'chunkIndexFilter'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const sortEl = document.getElementById('chunkSortFilter');
    if (sortEl) sortEl.value = 'chunk_id:desc';
    load(1);
  }

  async function refreshFilterControls(selectedDocId = '') {
    const docSelect = document.getElementById('chunkDocFilter');
    const previousDocId = docSelect?.value || '';
    try {
      const docsRes = await API.listDocuments({ page_size: 200, status: 'active' });
      const docs = docsRes?.data || [];
      if (docSelect) {
        docSelect.innerHTML = `
          <option value="">全部文档</option>
          ${docs.map(d => `<option value="${UI.escapeHtml(d.doc_id)}">${UI.escapeHtml(d.title || d.doc_id)}</option>`).join('')}
        `;
        const nextDocId = selectedDocId || previousDocId;
        if ([...docSelect.options].some((option) => option.value === nextDocId)) {
          docSelect.value = nextDocId;
        }
      }
    } catch (e) {
      // 文档下拉刷新失败不影响已创建的知识块展示。
    }

    try {
      const res = await API.searchFilters();
      filterOptions = res?.data || filterOptions;
      refreshFilterSelect('chunkIndexFilter', '全部索引状态', filterOptions.index_statuses || [], (s) => `${indexStatusLabel(s.value)} (${s.count || 0})`);
      refreshFilterSelect('chunkStatusFilter', '全部状态', filterOptions.chunk_statuses || [], (s) => `${chunkStatusLabel(s.value)} (${s.count || 0})`);
      refreshFilterSelect('chunkCategoryFilter', '全部分类', filterOptions.categories || [], (c) => `${c.value} (${c.count || 0})`);
      refreshFilterSelect('chunkTypeFilter', '全部类型', filterOptions.knowledge_types || [], (k) => `${UI.ktypeLabel(k.value)} (${k.count || 0})`);
    } catch (e) {
      // 筛选计数可稍后随页面刷新更新。
    }
  }

  function refreshFilterSelect(id, defaultLabel, options, labelFn) {
    const select = document.getElementById(id);
    if (!select) return;
    const previousValue = select.value;
    select.innerHTML = `
      <option value="">${defaultLabel}</option>
      ${options.map((option) => `<option value="${UI.escapeHtml(option.value)}">${UI.escapeHtml(labelFn(option))}</option>`).join('')}
    `;
    if ([...select.options].some((option) => option.value === previousValue)) {
      select.value = previousValue;
    }
  }

  function chunkStatusLabel(status) {
    const map = {
      active: '活跃',
      deleted: '已删除',
      superseded: '已替换',
    };
    return map[status] || status || '未知';
  }

  function indexStatusLabel(status) {
    const map = {
      pending: '待索引',
      indexed: '已索引',
      failed: '索引失败',
    };
    return map[status] || status || '未知';
  }

  /* -----------------------------------------------------------------------
     Detail — 知识块详情抽屉
     ----------------------------------------------------------------------- */
  async function showDetail(chunkId) {
    try {
      const res = await API.getChunk(chunkId);
      const c = res?.data || {};
      document.getElementById('chunkDetailTitle').textContent = c.title || '知识块详情';
      document.getElementById('chunkDetailBody').innerHTML = `
        <div class="detail-grid">
          <div class="detail-field"><label>ID</label><span style="font-family: var(--font-mono); font-size: var(--text-xs);">${UI.escapeHtml(c.chunk_id)}</span></div>
          <div class="detail-field"><label>文档</label><span>${UI.escapeHtml(c.doc_title || c.doc_id || '—')}</span></div>
          <div class="detail-field"><label>类型</label><span>${UI.ktypeBadge(c.knowledge_type)}</span></div>
          <div class="detail-field"><label>分类</label><span>${UI.escapeHtml(c.category || '未分类')}</span></div>
          <div class="detail-field"><label>状态</label><span>${UI.statusBadge(c.status || 'active')}</span></div>
          <div class="detail-field"><label>索引状态</label><span>${UI.statusBadge(c.index_status || 'pending')} ${c.index_error ? `<span style="color: var(--cinnabar); font-size: var(--text-xs);">(${UI.escapeHtml(c.index_error)})</span>` : ''}</span></div>
          <div class="detail-field"><label>内容哈希</label><span style="font-family: var(--font-mono); font-size: var(--text-xs);">${UI.escapeHtml(c.content_hash || '—')}</span></div>
        </div>
        <div class="detail-content">
          <h3>内容</h3>
          <pre>${UI.escapeHtml(c.content || '(无内容)')}</pre>
        </div>
        <div class="detail-actions" style="display: flex; gap: var(--space-2); margin-top: var(--space-6);">
          <button class="btn btn-secondary btn-sm" onclick="Chunks.showEditDialog('${c.chunk_id}')">编辑</button>
          <button class="btn btn-primary btn-sm" onclick="Chunks.reindexChunk('${c.chunk_id}')">⟳ 重建索引</button>
          ${c.status === 'deleted'
            ? `<button class="btn btn-success btn-sm" onclick="Chunks.restoreChunk('${c.chunk_id}')">恢复</button>`
            : `<button class="btn btn-danger btn-sm" onclick="Chunks.deleteChunk('${c.chunk_id}')">删除</button>`}
        </div>
      `;
      document.getElementById('chunkDetailDrawer').style.display = 'block';
    } catch (e) {
      UI.toast(`获取知识块详情失败: ${e.message}`, 'error');
    }
  }

  async function showEditDialog(chunkId) {
    try {
      const res = await API.getChunk(chunkId);
      const c = res?.data || {};
      UI.showModal(
        '编辑知识块',
        `
          <div class="form-stack create-chunk-form">
            <div id="editChunkFormError" class="form-error is-hidden"></div>
            <div>
              <label class="field-label">标题 <span>*</span></label>
              <input id="editChunkTitle" class="input" style="width: 100%;" value="${UI.escapeHtml(c.title || '')}" />
            </div>
            <div>
              <label class="field-label">分类</label>
              <input id="editChunkCategory" class="input" style="width: 100%;" value="${UI.escapeHtml(c.category || '通用')}" />
            </div>
            <div>
              <label class="field-label">类型</label>
              <select id="editChunkType" class="select" style="width: 100%;">
                <option value="declarative" ${c.knowledge_type === 'declarative' ? 'selected' : ''}>陈述型：事实、定义、说明</option>
                <option value="procedural" ${c.knowledge_type === 'procedural' ? 'selected' : ''}>流程型：步骤、操作方法</option>
                <option value="relational" ${c.knowledge_type === 'relational' ? 'selected' : ''}>关系型：实体关系、对应关系</option>
              </select>
            </div>
            <div>
              <label class="field-label">内容 <span>*</span></label>
              <textarea id="editChunkContent" class="textarea create-chunk-content" rows="8" style="width: 100%;">${UI.escapeHtml(c.content || '')}</textarea>
            </div>
            <label class="check-control create-chunk-index-option">
              <input type="checkbox" id="editChunkReindex" checked />
              <span>
                保存后重建索引
                <small>内容变化后建议保持勾选，确保检索结果同步更新。</small>
              </span>
            </label>
          </div>
        `,
        `
          <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
          <button class="btn btn-primary" onclick="Chunks.updateChunkFromDialog('${chunkId}')">保存修改</button>
        `
      );
    } catch (e) {
      UI.toast(`加载知识块失败: ${e.message}`, 'error');
    }
  }

  async function updateChunkFromDialog(chunkId) {
    const title = document.getElementById('editChunkTitle')?.value?.trim();
    const content = document.getElementById('editChunkContent')?.value?.trim();
    const category = document.getElementById('editChunkCategory')?.value?.trim() || '通用';
    const knowledgeType = document.getElementById('editChunkType')?.value || 'declarative';
    const reindex = Boolean(document.getElementById('editChunkReindex')?.checked);
    const errorEl = document.getElementById('editChunkFormError');
    if (!title || !content || content.length < 10) {
      if (errorEl) {
        errorEl.textContent = !title ? '请输入知识块标题。' : '知识块内容至少需要 10 个字。';
        errorEl.classList.remove('is-hidden');
      }
      return;
    }

    try {
      await API.updateChunk(chunkId, {
        title,
        content,
        category,
        knowledge_type: knowledgeType,
        reindex,
      });
      UI.toast('知识块已更新', 'success');
      document.querySelector('.modal-backdrop:last-child')?.remove();
      closeDrawer();
      await load(currentPage);
    } catch (e) {
      if (errorEl) {
        errorEl.textContent = e.message || '保存失败';
        errorEl.classList.remove('is-hidden');
      }
      UI.toast(`保存失败: ${e.message}`, 'error');
    }
  }

  function closeDrawer() {
    document.getElementById('chunkDetailDrawer').style.display = 'none';
  }

  /* -----------------------------------------------------------------------
     CRUD 操作
     ----------------------------------------------------------------------- */
  async function showCreateDialog() {
    let documents = [];
    let docLoadError = '';
    try {
      const docsRes = await API.listDocuments({ page_size: 200, status: 'active' });
      documents = docsRes?.data || [];
    } catch (e) {
      docLoadError = e.message || '文档列表加载失败';
    }

    const useExistingChecked = docLoadError ? '' : 'checked';
    const useNewChecked = docLoadError ? 'checked' : '';
    const docOptions = documents.map((d) => `
      <option value="${UI.escapeHtml(d.doc_id)}">${UI.escapeHtml(d.title || d.doc_id)} · ${UI.escapeHtml(d.doc_id)}</option>
    `).join('');
    const categories = ['通用', ...((filterOptions.categories || []).map((c) => c.value).filter(Boolean))]
      .filter((value, index, arr) => arr.indexOf(value) === index);
    previousCreateDocCategory = categories[0] || '通用';
    const categoryOptions = categories.map((c) => `
      <option value="${UI.escapeHtml(c)}">${UI.escapeHtml(c)}</option>
    `).join('');

    UI.showModal(
      '新建知识块',
      `
        <div class="form-stack create-chunk-form">
          <div id="newChunkFormError" class="form-error is-hidden"></div>

          <div>
            <label class="field-label">归属文档 <span>*</span></label>
            <div class="mode-switch create-doc-mode">
              <label>
                <input type="radio" name="newChunkDocMode" value="existing" ${useExistingChecked} ${docLoadError ? 'disabled' : ''} onchange="Chunks.toggleCreateDocMode()">
                <span>选择已有文档</span>
              </label>
              <label>
                <input type="radio" name="newChunkDocMode" value="new" ${useNewChecked} onchange="Chunks.toggleCreateDocMode()">
                <span>新建文档</span>
              </label>
            </div>
          </div>

          <div id="existingDocPanel">
            <select id="newChunkDocId" class="select" style="width: 100%;" ${docLoadError ? 'disabled' : ''}>
              <option value="">${docLoadError ? '文档列表加载失败' : '选择一个已入库文档'}</option>
              ${docOptions}
            </select>
            <div class="${docLoadError ? 'field-warning' : 'field-help'}">
              ${docLoadError ? `${UI.escapeHtml(docLoadError)}，仍可切换到“新建文档”继续创建。` : '知识块会挂到所选文档下，用于后续筛选、溯源和版本管理。'}
            </div>
          </div>

          <div id="newDocPanel" class="is-hidden">
            <div class="form-grid create-doc-grid">
              <div>
                <label class="field-label">新文档标题 <span>*</span></label>
                <input id="newChunkDocTitle" class="input" style="width: 100%;" placeholder="例如：人工补充知识" />
              </div>
              <div>
                <label class="field-label">文档分类 <span>(选择已有或新增)</span></label>
                <select id="newChunkDocCategorySelect" class="select" style="width: 100%;" onchange="Chunks.onCreateDocCategorySelect()">
                  ${categoryOptions}
                  <option value="__custom__">+ 新增分类...</option>
                </select>
              </div>
            </div>
            <div class="field-help">会先创建一个手工文档，再把当前知识块挂到这个新文档下。</div>
          </div>

          <div>
            <label class="field-label">标题 <span>*</span></label>
            <input id="newChunkTitle" class="input" style="width: 100%;" placeholder="例如：退货申请条件" />
          </div>

          <div>
            <div class="field-label-row">
              <label class="field-label">内容 <span>*</span></label>
              <span id="newChunkContentCount" class="field-counter">0 字</span>
            </div>
            <textarea id="newChunkContent" class="textarea create-chunk-content" rows="7" style="width: 100%;"
                      placeholder="输入一段可以独立回答问题的知识内容，例如规则、定义、步骤或限制条件。"
                      oninput="Chunks.updateCreateFormState()"></textarea>
          </div>

          <div>
            <label class="field-label">知识块分类</label>
            <select id="newChunkCategory" class="select" style="width: 100%;">
              ${categoryOptions}
            </select>
          </div>

          <div>
            <label class="field-label">类型</label>
            <select id="newChunkType" class="select" style="width: 100%;">
              <option value="declarative">陈述型：事实、定义、说明</option>
              <option value="procedural">流程型：步骤、操作方法</option>
              <option value="relational">关系型：实体关系、对应关系</option>
            </select>
          </div>

          <label class="check-control create-chunk-index-option">
            <input type="checkbox" id="newChunkIndexAfterCreate" />
            <span>
              创建后立即加入检索索引
              <small>需要 embedding 配置可用；不勾选时可稍后手动重建索引。</small>
            </span>
          </label>

          <div id="newChunkCategoryDialog" class="mini-dialog-backdrop is-hidden" role="dialog" aria-modal="true" aria-labelledby="newChunkCategoryDialogTitle">
            <div class="mini-dialog">
              <div class="mini-dialog-header">
                <h3 id="newChunkCategoryDialogTitle">新增文档分类</h3>
                <button type="button" class="btn-close" onclick="Chunks.cancelCreateDocCategory()">&times;</button>
              </div>
              <div class="mini-dialog-body">
                <label class="field-label">分类名称</label>
                <input id="newChunkCategoryDialogInput" class="input" style="width: 100%;" placeholder="例如：售后政策"
                       onkeydown="if(event.key==='Enter')Chunks.confirmCreateDocCategory();if(event.key==='Escape')Chunks.cancelCreateDocCategory();">
                <div id="newChunkCategoryDialogError" class="field-warning is-hidden">请输入分类名称。</div>
              </div>
              <div class="mini-dialog-footer">
                <button type="button" class="btn btn-secondary btn-sm" onclick="Chunks.cancelCreateDocCategory()">取消</button>
                <button type="button" class="btn btn-primary btn-sm" onclick="Chunks.confirmCreateDocCategory()">确认</button>
              </div>
            </div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
        <button class="btn btn-primary" id="confirmCreateChunkBtn">创建知识块</button>
      `
    );

    // 绑定创建按钮事件
    setTimeout(() => {
      updateCreateFormState();
      toggleCreateDocMode();
      ['newChunkDocId', 'newChunkDocTitle', 'newChunkDocCategorySelect', 'newChunkTitle', 'newChunkContent'].forEach((id) => {
        document.getElementById(id)?.addEventListener('input', updateCreateFormState);
        document.getElementById(id)?.addEventListener('change', updateCreateFormState);
      });

      document.getElementById('confirmCreateChunkBtn')?.addEventListener('click', async () => {
        const useNewDoc = isCreateNewDocumentMode();
        let docId = document.getElementById('newChunkDocId')?.value?.trim();
        const docTitle = document.getElementById('newChunkDocTitle')?.value?.trim();
        const docCategory = getCreateDocCategory();
        const title = document.getElementById('newChunkTitle')?.value?.trim();
        const content = document.getElementById('newChunkContent')?.value?.trim();
        const chunkCategory = document.getElementById('newChunkCategory')?.value?.trim() || docCategory || '通用';
        const indexAfterCreate = Boolean(document.getElementById('newChunkIndexAfterCreate')?.checked);
        const error = validateCreateForm({ useNewDoc, docId, docTitle, docCategory, title, content });
        if (error) {
          showCreateFormError(error);
          return;
        }

        const btn = document.getElementById('confirmCreateChunkBtn');
        if (btn) {
          btn.disabled = true;
          btn.textContent = '创建中...';
        }

        try {
          if (useNewDoc) {
            const docRes = await API.createDocument({
              title: docTitle,
              source_type: 'manual',
              source_uri: `manual://chunk-dialog/${Date.now()}`,
              category: docCategory,
              metadata: JSON.stringify({ manual: true, created_from: 'chunk_dialog' }),
            });
            docId = docRes?.data?.doc_id;
            if (!docId) throw new Error('新文档创建成功，但未返回文档 ID');
          }

          await API.createChunk({
            doc_id: docId,
            title,
            content,
            knowledge_type: document.getElementById('newChunkType')?.value,
            category: chunkCategory,
            index_after_create: indexAfterCreate,
          });
          UI.toast('知识块创建成功', 'success');
          document.querySelector('.modal-backdrop')?.remove();
          await refreshFilterControls(useNewDoc ? docId : '');
          await load(1);
        } catch (e) {
          showCreateFormError(e.message || '创建失败');
          UI.toast(`创建失败: ${e.message}`, 'error');
        } finally {
          if (btn) {
            btn.disabled = false;
            btn.textContent = '创建知识块';
          }
        }
      });
    }, 100);
  }

  function validateCreateForm({ useNewDoc, docId, docTitle, docCategory, title, content }) {
    if (useNewDoc && !docTitle) return '请输入新文档标题。';
    if (useNewDoc && !docCategory) return '请选择或输入文档分类。';
    if (!useNewDoc && !docId) return '请选择归属文档。';
    if (!title) return '请输入知识块标题。';
    if (!content) return '请输入知识块内容。';
    if (content.length < 10) return '知识块内容至少需要 10 个字，方便后续检索和重排。';
    return '';
  }

  function showCreateFormError(message) {
    const el = document.getElementById('newChunkFormError');
    if (!el) return;
    el.textContent = message;
    el.classList.remove('is-hidden');
  }

  function isCreateNewDocumentMode() {
    return document.querySelector('input[name="newChunkDocMode"]:checked')?.value === 'new';
  }

  function getCreateDocCategory() {
    const select = document.getElementById('newChunkDocCategorySelect');
    return select?.value?.trim() || '通用';
  }

  function onCreateDocCategorySelect() {
    const select = document.getElementById('newChunkDocCategorySelect');
    if (!select) return;
    if (select.value === '__custom__') {
      select.value = previousCreateDocCategory;
      showCreateDocCategoryDialog();
      return;
    }
    previousCreateDocCategory = select.value || '通用';
    updateCreateFormState();
  }

  function showCreateDocCategoryDialog() {
    const dialog = document.getElementById('newChunkCategoryDialog');
    const input = document.getElementById('newChunkCategoryDialogInput');
    const error = document.getElementById('newChunkCategoryDialogError');
    if (!dialog || !input) return;
    input.value = '';
    if (error) error.classList.add('is-hidden');
    dialog.classList.remove('is-hidden');
    setTimeout(() => input.focus(), 0);
  }

  function cancelCreateDocCategory() {
    const dialog = document.getElementById('newChunkCategoryDialog');
    const select = document.getElementById('newChunkDocCategorySelect');
    if (dialog) dialog.classList.add('is-hidden');
    if (select) select.value = previousCreateDocCategory;
    updateCreateFormState();
  }

  function confirmCreateDocCategory() {
    const select = document.getElementById('newChunkDocCategorySelect');
    const input = document.getElementById('newChunkCategoryDialogInput');
    const error = document.getElementById('newChunkCategoryDialogError');
    if (!select || !input) return;
    const value = input.value.trim();
    if (!value) {
      if (error) error.classList.remove('is-hidden');
      input.focus();
      return;
    }

    const existing = [...select.options].find((option) => option.value === value);
    if (!existing) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      const customOption = select.querySelector('option[value="__custom__"]');
      select.insertBefore(option, customOption);
    }
    select.value = value;
    const chunkCategorySelect = document.getElementById('newChunkCategory');
    if (chunkCategorySelect && ![...chunkCategorySelect.options].some((option) => option.value === value)) {
      const chunkOption = document.createElement('option');
      chunkOption.value = value;
      chunkOption.textContent = value;
      chunkCategorySelect.appendChild(chunkOption);
    }
    if (chunkCategorySelect) chunkCategorySelect.value = value;
    previousCreateDocCategory = value;
    cancelCreateDocCategory();
  }

  function toggleCreateDocMode() {
    const useNewDoc = isCreateNewDocumentMode();
    const existingPanel = document.getElementById('existingDocPanel');
    const newPanel = document.getElementById('newDocPanel');
    if (existingPanel) existingPanel.classList.toggle('is-hidden', useNewDoc);
    if (newPanel) newPanel.classList.toggle('is-hidden', !useNewDoc);
    updateCreateFormState();
  }

  function updateCreateFormState() {
    const useNewDoc = isCreateNewDocumentMode();
    const docId = document.getElementById('newChunkDocId')?.value?.trim();
    const docTitle = document.getElementById('newChunkDocTitle')?.value?.trim();
    const docCategory = getCreateDocCategory();
    const title = document.getElementById('newChunkTitle')?.value?.trim();
    const content = document.getElementById('newChunkContent')?.value?.trim() || '';
    const counter = document.getElementById('newChunkContentCount');
    const btn = document.getElementById('confirmCreateChunkBtn');
    const error = document.getElementById('newChunkFormError');

    if (counter) counter.textContent = `${content.length} 字`;
    if (btn && !btn.textContent.includes('创建中')) {
      btn.disabled = (useNewDoc ? (!docTitle || !docCategory) : !docId) || !title || content.length < 10;
    }
    if (error) error.classList.add('is-hidden');
  }

  async function deleteChunk(chunkId) {
    if (!confirm('确认软删除该知识块？')) return;
    try {
      await API.deleteChunk(chunkId);
      UI.toast('知识块已删除', 'success');
      await load();
    } catch (e) {
      UI.toast(`删除失败: ${e.message}`, 'error');
    }
  }

  async function restoreChunk(chunkId) {
    try {
      await API.restoreChunk(chunkId);
      UI.toast('知识块已恢复', 'success');
      await load();
    } catch (e) {
      UI.toast(`恢复失败: ${e.message}`, 'error');
    }
  }

  async function reindexChunk(chunkId) {
    try {
      await API.reindexChunk(chunkId);
      UI.toast('重建索引成功', 'success');
      await load();
    } catch (e) {
      UI.toast(`重建索引失败: ${e.message}`, 'error');
    }
  }

  /* -----------------------------------------------------------------------
     Batch — 批量操作
     ----------------------------------------------------------------------- */
  function toggleSelectAll() {
    const checkboxes = document.querySelectorAll('.chunk-checkbox');
    const selectAll = document.getElementById('chunkSelectAll');
    checkboxes.forEach(cb => {
      cb.checked = selectAll.checked;
      if (selectAll.checked) selectedIds.add(cb.value);
      else selectedIds.delete(cb.value);
    });
    updateBatchBtn();
  }

  function toggleSelect(e) {
    if (e.target.checked) selectedIds.add(e.target.value);
    else selectedIds.delete(e.target.value);
    updateBatchBtn();
  }

  function updateBatchBtn() {
    const deleteBtn = document.getElementById('batchDeleteChunkBtn');
    const reindexBtn = document.getElementById('batchReindexChunkBtn');
    if (deleteBtn) deleteBtn.disabled = selectedIds.size === 0;
    if (reindexBtn) reindexBtn.disabled = selectedIds.size === 0;
  }

  async function batchReindex() {
    if (!selectedIds.size) return;
    if (!confirm(`确认为 ${selectedIds.size} 个知识块重建索引？`)) return;
    try {
      await API.batchReindexChunks([...selectedIds]);
      UI.toast(`已提交 ${selectedIds.size} 个知识块重建索引`, 'success');
      selectedIds.clear();
      await load();
    } catch (e) {
      UI.toast(`批量重建索引失败: ${e.message}`, 'error');
    }
  }

  async function batchDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`确认批量删除 ${selectedIds.size} 个知识块？`)) return;
    try {
      await API.batchChunkOperation('delete', [...selectedIds]);
      UI.toast(`批量删除完成: ${selectedIds.size} 个知识块`, 'success');
      selectedIds.clear();
      await load();
    } catch (e) {
      UI.toast(`批量删除失败: ${e.message}`, 'error');
    }
  }

  return { render, load, showDetail, closeDrawer, showEditDialog, updateChunkFromDialog, showCreateDialog, toggleCreateDocMode, onCreateDocCategorySelect, cancelCreateDocCategory, confirmCreateDocCategory, updateCreateFormState, deleteChunk, restoreChunk, reindexChunk, toggleSelectAll, toggleSelect, batchReindex, batchDelete, resetFilters };
})();
