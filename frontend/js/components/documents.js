/* ==========================================================================
   文档管理组件 — 列表、上传、删除、恢复、入库（已迁移至 v1 API）
   ========================================================================== */

const Documents = (() => {

  let currentPage = 1;
  let currentKeyword = '';
  let currentStatus = '';
  let currentCategory = '';
  let selectedIds = new Set();
  let categoryOptions = [];  // 从后端动态加载的分类列表

  async function renderList() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '文档管理' }]);
    UI.render(`<div class="loading-overlay"><div class="loading-spinner"></div><span>加载文档列表…</span></div>`);

    // 动态加载分类选项
    try {
      const res = await API.searchFilters();
      categoryOptions = (res?.data?.categories || []).map(c => c.value);
    } catch (e) { categoryOptions = []; }

    await loadPage(1);
  }

  async function loadPage(page) {
    currentPage = page;
    try {
      const params = {
        page,
        page_size: 15,
        keyword: currentKeyword || undefined,
        status: currentStatus || undefined,
        category: currentCategory || undefined,
        sort_by: 'updated_at',
        sort_order: 'desc',
      };
      const res = await API.listDocuments(params);
      renderDocListHtml(res);
    } catch (e) {
      UI.toast(`加载文档失败: ${e.message}`, 'error');
      renderDocListHtml(null);
    }
  }

  function renderDocListHtml(res) {
    const items = res?.data || [];
    const meta = res?.meta || {};
    const total = meta.total || 0;
    const totalPages = meta.total_pages || 1;

    let rowsHtml = '';
    if (items.length === 0) {
      rowsHtml = `
        <tr><td colspan="7">
          <div class="empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-title">暂无文档</div>
            <div class="empty-state-desc">点击右上角「上传文档」按钮导入文档。支持 Markdown、DOCX、XLSX、HTML、PDF、PPTX 等格式。</div>
            <button class="btn btn-primary" onclick="Documents.showUploadModal()" style="margin-top: var(--space-4);">↑ 上传第一篇文档</button>
          </div>
        </td></tr>`;
    } else {
      rowsHtml = items.map(doc => `
        <tr>
          <td><input type="checkbox" value="${doc.doc_id}" class="doc-checkbox" onclick="Documents.toggleSelect(event)" /></td>
          <td>
            <div class="doc-title-cell">
              ${UI.fmtBadge(doc.source_type)}
              <span class="doc-title-link" onclick="App.router.navigate('/documents/${UI.escapeHtml(doc.doc_id)}')">
                ${UI.escapeHtml(doc.title || '未命名文档')}
              </span>
            </div>
          </td>
          <td>${UI.escapeHtml(doc.category || '通用')}</td>
          <td>${UI.statusBadge(doc.status || 'active')}</td>
          <td>${doc.chunk_count ?? '—'} / ${doc.element_count ?? '—'}</td>
          <td>${UI.formatTime(doc.updated_at) || UI.formatTime(doc.created_at)}</td>
          <td class="actions-cell">
            <button class="btn btn-sm btn-ghost" onclick="App.router.navigate('/documents/${UI.escapeHtml(doc.doc_id)}')">详情</button>
            ${doc.status === 'deleted'
              ? `<button class="btn btn-sm btn-success" onclick="Documents.restoreDoc('${doc.doc_id}')">恢复</button>`
              : `<button class="btn btn-sm btn-danger" onclick="Documents.deleteDoc('${doc.doc_id}')">删除</button>`}
          </td>
        </tr>
      `).join('');
    }

    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">文档管理</h1>
            <p class="page-subtitle">管理已入库的文档，查看解析结果和知识块</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline btn-sm" onclick="Documents.batchDelete()" id="batchDeleteDocBtn" disabled>批量删除</button>
            <button class="btn btn-primary" onclick="Documents.showUploadModal()">↑ 上传文档</button>
          </div>
        </div>
      </div>

      <!-- 搜索过滤 -->
      <div class="doc-toolbar kb-filter-bar">
        <input class="input kb-toolbar-search" type="text" id="docSearchInput" placeholder="搜索文档标题…" value="${UI.escapeHtml(currentKeyword)}"
               onkeydown="if(event.key==='Enter')Documents.doSearch()">
        <select class="select select-sm" id="docCategoryFilter" onchange="Documents.doSearch()">
          <option value="">全部分类</option>
          ${categoryOptions.map(c => `<option value="${UI.escapeHtml(c)}" ${currentCategory === c ? 'selected' : ''}>${UI.escapeHtml(c)}</option>`).join('')}
        </select>
        <select class="select select-sm" id="docStatusFilter" onchange="Documents.doSearch()">
          <option value="">全部状态</option>
          <option value="active" ${currentStatus === 'active' ? 'selected' : ''}>活跃</option>
          <option value="pending" ${currentStatus === 'pending' ? 'selected' : ''}>待处理</option>
          <option value="processing" ${currentStatus === 'processing' ? 'selected' : ''}>处理中</option>
          <option value="failed" ${currentStatus === 'failed' ? 'selected' : ''}>失败</option>
          <option value="deleted" ${currentStatus === 'deleted' ? 'selected' : ''}>已删除</option>
        </select>
        <button class="btn btn-secondary btn-sm" onclick="Documents.doSearch()">查询</button>
        <span class="doc-count">共 ${total} 篇文档</span>
      </div>

      <!-- 文档表格 -->
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width: 3%;"><input type="checkbox" id="docSelectAll" onclick="Documents.toggleSelectAll()" /></th>
              <th style="width: 35%;">文档名称</th>
              <th style="width: 10%;">分类</th>
              <th style="width: 10%;">状态</th>
              <th style="width: 10%;">知识块/元素</th>
              <th style="width: 18%;">更新时间</th>
              <th style="width: 14%;">操作</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>

      <!-- 分页 -->
      ${totalPages > 1 ? `
      <div class="pagination">
        <button class="btn btn-sm btn-secondary" onclick="Documents.loadPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>‹ 上一页</button>
        <span class="pagination-info">${currentPage} / ${totalPages}（共 ${total} 篇）</span>
        <button class="btn btn-sm btn-secondary" onclick="Documents.loadPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一页 ›</button>
      </div>` : ''}
    `);
  }

  /* -----------------------------------------------------------------------
     搜索与过滤
     ----------------------------------------------------------------------- */
  function doSearch() {
    currentKeyword = document.getElementById('docSearchInput')?.value?.trim() || '';
    currentCategory = document.getElementById('docCategoryFilter')?.value || '';
    currentStatus = document.getElementById('docStatusFilter')?.value || '';
    loadPage(1);
  }

  /* -----------------------------------------------------------------------
     CRUD 操作（v1）
     ----------------------------------------------------------------------- */
  async function deleteDoc(docId) {
    if (!confirm('确认软删除该文档？关联知识块将同步标记为删除。')) return;
    try {
      await API.deleteDocument(docId);
      UI.toast('文档已删除', 'success');
      loadPage(currentPage);
    } catch (e) {
      UI.toast(`删除失败: ${e.message}`, 'error');
    }
  }

  async function restoreDoc(docId) {
    try {
      await API.restoreDocument(docId);
      UI.toast('文档已恢复', 'success');
      loadPage(currentPage);
    } catch (e) {
      UI.toast(`恢复失败: ${e.message}`, 'error');
    }
  }

  async function ingestDocument(docId) {
    try {
      await API.ingestDocument(docId, 'force');
      UI.toast('已触发重新入库', 'success');
    } catch (e) {
      UI.toast(`重新入库失败: ${e.message}`, 'error');
    }
  }

  /* -----------------------------------------------------------------------
     批量操作
     ----------------------------------------------------------------------- */
  function toggleSelectAll() {
    const checkboxes = document.querySelectorAll('.doc-checkbox');
    const selectAll = document.getElementById('docSelectAll');
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
    const btn = document.getElementById('batchDeleteDocBtn');
    if (btn) btn.disabled = selectedIds.size === 0;
  }

  async function batchDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`确认批量删除 ${selectedIds.size} 篇文档？`)) return;
    let done = 0;
    for (const id of selectedIds) {
      try { await API.deleteDocument(id); done++; } catch (e) { /* skip */ }
    }
    UI.toast(`批量删除完成: ${done}/${selectedIds.size}`, 'success');
    selectedIds.clear();
    loadPage(currentPage);
  }

  /* -----------------------------------------------------------------------
     上传页面（使用旧 upload 接口——上传链路暂不迁移）
     ----------------------------------------------------------------------- */
  let selectedFile = null;

  async function showUploadModal() {
    // 加载已有分类
    let existingCategories = [];
    try {
      const res = await API.searchFilters();
      existingCategories = (res?.data?.categories || []).map(c => c.value);
    } catch (e) { /* ignore */ }

    UI.showModal(
      '上传文档',
      `
        <div class="upload-zone" id="uploadZone" style="border: 2px dashed var(--mist); border-radius: var(--radius-lg); padding: var(--space-6); text-align: center; cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out);">
          <span style="font-size: 2.5rem;">📁</span>
          <div style="font-weight: 550; margin-top: var(--space-2);">拖拽文件到此处，或点击选择</div>
          <div style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: var(--space-1);">单个文件最大 100 MB，支持 Markdown、DOCX、XLSX、HTML、PDF、PPTX 格式</div>
          <input type="file" id="fileInput" style="display: none;" accept=".md,.txt,.docx,.xlsx,.html,.htm,.pdf,.pptx">
          <button class="btn btn-primary" onclick="document.getElementById('fileInput').click();event.stopPropagation()" style="margin-top: var(--space-3);">选择文件</button>
          <div style="display: flex; gap: var(--space-1); justify-content: center; margin-top: var(--space-3);">
            <span class="badge-fmt md">MD</span><span class="badge-fmt docx">DOCX</span><span class="badge-fmt xlsx">XLSX</span>
            <span class="badge-fmt html">HTML</span><span class="badge-fmt pdf">PDF</span><span class="badge-fmt pptx">PPTX</span>
          </div>
        </div>

        <div id="fileInfo" style="display: none; margin-top: var(--space-4);">
          <div class="card">
            <div style="display: flex; align-items: center; gap: var(--space-3);">
              <span style="font-size: 1.5rem;">📄</span>
              <div style="flex: 1;">
                <div style="font-weight: 550;" id="fileNameDisplay">—</div>
                <div style="font-size: var(--text-xs); color: var(--ink-wash);" id="fileSizeDisplay">—</div>
              </div>
              <button class="btn btn-sm btn-ghost" onclick="Documents.clearFile()">✕</button>
            </div>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); margin-top: var(--space-3);">
            <div>
              <label class="field-label">文档标题 <span>(可选)</span></label>
              <input class="input" type="text" id="docTitle" placeholder="留空则使用文件名" style="width: 100%;">
            </div>
            <div>
              <label class="field-label">分类 <span>(选择已有或输入新分类)</span></label>
              <select class="select" id="docCategorySelect" onchange="Documents.onCategorySelect()" style="width: 100%;">
                <option value="通用">通用</option>
                ${existingCategories.map(c => `<option value="${UI.escapeHtml(c)}">${UI.escapeHtml(c)}</option>`).join('')}
                <option value="__custom__">✚ 新增分类…</option>
              </select>
              <input class="input" type="text" id="docCategoryInput" placeholder="输入新分类名称" style="width: 100%; margin-top: var(--space-2); display: none;">
            </div>
          </div>

          <div id="uploadProgress" style="display: none; margin-top: var(--space-4);">
            <div class="upload-progress-bar"><div class="upload-progress-fill" id="uploadProgressFill" style="width: 0%;"></div></div>
            <div class="upload-progress-text" id="uploadProgressText">上传中…</div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="Documents.closeUploadModal()">取消</button>
        <button class="btn btn-primary" id="uploadBtn" onclick="Documents.doUpload()">↑ 开始上传并入库</button>
      `
    );

    selectedFile = null;
    document.getElementById('fileInfo').style.display = 'none';

    setTimeout(() => bindUploadEvents(), 50);
  }

  function onCategorySelect() {
    const select = document.getElementById('docCategorySelect');
    const input = document.getElementById('docCategoryInput');
    if (!select || !input) return;
    if (select.value === '__custom__') {
      input.style.display = 'block';
      input.focus();
    } else {
      input.style.display = 'none';
    }
  }

  function closeUploadModal() {
    const backdrop = document.querySelector('.modal-backdrop');
    if (backdrop) backdrop.remove();
  }

  function bindUploadEvents() {
    const zone = document.getElementById('uploadZone');
    const input = document.getElementById('fileInput');
    if (!zone || !input) return;
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault(); zone.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) selectFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => { if (input.files.length > 0) selectFile(input.files[0]); });
  }

  function selectFile(file) {
    if (file.size > 100 * 1024 * 1024) { UI.toast('文件大小超过 100 MB 限制', 'error'); return; }
    selectedFile = file;
    document.getElementById('fileInfo').style.display = 'block';
    document.getElementById('fileNameDisplay').textContent = file.name;
    document.getElementById('fileSizeDisplay').textContent = UI.formatSize(file.size);
  }

  function clearFile() {
    selectedFile = null;
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('fileInput').value = '';
  }

  async function doUpload() {
    if (!selectedFile) { UI.toast('请先选择文件', 'error'); return; }
    const title = document.getElementById('docTitle')?.value?.trim() || '';
    const categorySelect = document.getElementById('docCategorySelect');
    const categoryInput = document.getElementById('docCategoryInput');
    let category = '通用';
    if (categorySelect) {
      if (categorySelect.value === '__custom__') {
        category = categoryInput?.value?.trim() || '通用';
      } else {
        category = categorySelect.value;
      }
    }
    const btn = document.getElementById('uploadBtn');
    const progressDiv = document.getElementById('uploadProgress');
    const progressFill = document.getElementById('uploadProgressFill');
    const progressText = document.getElementById('uploadProgressText');

    btn.disabled = true; btn.textContent = '上传中…';
    progressDiv.style.display = 'block';
    progressFill.style.width = '30%'; progressText.textContent = '正在上传文件…';

    try {
      const result = await API.uploadFile(selectedFile, title, category);
      progressFill.style.width = '60%'; progressText.textContent = '上传完成，正在提交入库…';

      await API.submitIngest([{
        title: title || selectedFile.name,
        source_type: detectSourceType(selectedFile.name),
        source_uri: result.source_uri,
        source_hash: result.source_hash,
        category: category,
      }]);

      progressFill.style.width = '100%'; progressText.textContent = '入库任务已提交！';
      UI.toast(`文档 "${title || selectedFile.name}" 已上传并提交入库`, 'success');
      setTimeout(() => {
        closeUploadModal();
        loadPage(currentPage);
      }, 1000);
    } catch (e) {
      progressText.textContent = `失败: ${e.message}`;
      UI.toast(`上传失败: ${e.message}`, 'error');
      btn.disabled = false; btn.textContent = '↑ 重试上传';
    }
  }

  function detectSourceType(filename) {
    const ext = (filename || '').split('.').pop()?.toLowerCase();
    const map = { md: 'markdown', txt: 'text', docx: 'docx', xlsx: 'xlsx', html: 'html', htm: 'html', pdf: 'pdf', pptx: 'pptx' };
    return map[ext] || 'unknown';
  }

  return { renderList, showUploadModal, closeUploadModal, onCategorySelect, doSearch, loadPage, deleteDoc, restoreDoc, ingestDocument, toggleSelectAll, toggleSelect, batchDelete, selectFile, clearFile, doUpload };
})();
