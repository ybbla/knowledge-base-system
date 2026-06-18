/* ==========================================================================
   文档管理组件 — 列表、上传、删除、恢复、入库（已迁移至 v1 API）
   ========================================================================== */

const Documents = (() => {

  let currentPage = 1;
  let currentKeyword = '';
  let currentStatus = '';
  let currentCategory = '';
  let currentSort = 'updated_at:desc';
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
      const [sortBy, sortOrder] = currentSort.split(':');
      const params = {
        page,
        page_size: 15,
        keyword: currentKeyword || undefined,
        status: currentStatus || undefined,
        category: currentCategory || undefined,
        sort_by: sortBy || 'updated_at',
        sort_order: sortOrder || 'desc',
      };
      const res = await API.listDocuments(params);
      renderDocListHtml(res);
    } catch (e) {
      const message = friendlyErrorMessage(e);
      UI.toast(`加载文档失败：${message}`, 'error');
      renderDocListHtml(null, { errorMessage: message });
    }
  }

  function renderDocListHtml(res, state = {}) {
    selectedIds.clear();
    const items = res?.data || [];
    const meta = res?.meta || {};
    const total = meta.total || 0;
    const totalPages = meta.total_pages || 1;
    const hasFilters = Boolean(currentKeyword || currentCategory || currentStatus);
    const errorMessage = state.errorMessage || '';

    let rowsHtml = '';
    if (errorMessage) {
      rowsHtml = `
        <tr class="empty-row"><td colspan="7">
          <div class="empty-state empty-state-error">
            <div class="empty-state-icon">!</div>
            <div class="empty-state-title">文档列表加载失败</div>
            <div class="empty-state-desc">${UI.escapeHtml(errorMessage)}</div>
            <div class="empty-actions">
              <button class="btn btn-primary" onclick="Documents.loadPage(${currentPage})">重新加载</button>
            </div>
          </div>
        </td></tr>`;
    } else if (items.length === 0) {
      rowsHtml = `
        <tr class="empty-row"><td colspan="7">
          <div class="empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-title">${hasFilters ? '未找到匹配文档' : '暂无文档'}</div>
            <div class="empty-state-desc">${hasFilters
              ? '当前筛选条件下没有文档。可以调整关键词、分类或状态后再试。'
              : '上传文档后，可在这里查看解析结果、知识块数量和处理状态。支持 Markdown、TXT、DOCX、XLSX、HTML、PDF、PPTX 等格式。'}</div>
            <div class="empty-actions">
              ${hasFilters ? '<button class="btn btn-secondary" onclick="Documents.resetFilters()">清空筛选</button>' : ''}
              <button class="btn btn-primary" onclick="Documents.showUploadModal()">↑ 上传文档</button>
            </div>
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
          <td>
            <div class="doc-metrics">
              <span><strong>${doc.chunk_count ?? 0}</strong> 块</span>
              <span><strong>${doc.element_count ?? 0}</strong> 元素</span>
              <span><strong>${doc.asset_count ?? 0}</strong> 资源</span>
            </div>
          </td>
          <td>${UI.formatTime(doc.updated_at) || UI.formatTime(doc.created_at)}</td>
          <td class="actions-cell">
            <button class="btn btn-sm btn-ghost" onclick="App.router.navigate('/documents/${UI.escapeHtml(doc.doc_id)}')">详情</button>
            ${doc.status === 'deleted'
              ? `<button class="btn btn-sm btn-success" onclick="Documents.restoreDoc('${doc.doc_id}')">恢复</button>`
              : `
                <button class="btn btn-sm btn-ghost" onclick="Documents.showEditDialog('${doc.doc_id}')">编辑</button>
                <button class="btn btn-sm btn-ghost" onclick="Documents.ingestDocument('${doc.doc_id}')">重处理</button>
                <button class="btn btn-sm btn-danger" onclick="Documents.deleteDoc('${doc.doc_id}')">删除</button>
              `}
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
      <div class="doc-toolbar kb-filter-bar document-filter-bar">
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
        <select class="select select-sm" id="docSortFilter" onchange="Documents.doSearch()">
          <option value="updated_at:desc" ${currentSort === 'updated_at:desc' ? 'selected' : ''}>更新时间</option>
          <option value="title:asc" ${currentSort === 'title:asc' ? 'selected' : ''}>标题 A-Z</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="Documents.resetFilters()" ${hasFilters ? '' : 'disabled'}>清空筛选</button>
        <span class="doc-count">${errorMessage ? '' : `共 ${total} 篇文档`}</span>
      </div>

      <!-- 文档表格 -->
      <div class="table-wrap">
        <table class="doc-table">
          <thead>
            <tr>
              <th style="width: 3%;"><input type="checkbox" id="docSelectAll" onclick="Documents.toggleSelectAll()" ${items.length === 0 ? 'disabled' : ''} /></th>
              <th style="width: 30%;">文档名称</th>
              <th style="width: 10%;">分类</th>
              <th style="width: 9%;">状态</th>
              <th style="width: 13%;">解析结果</th>
              <th style="width: 16%;">更新时间</th>
              <th style="width: 19%;">操作</th>
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
    currentSort = document.getElementById('docSortFilter')?.value || 'updated_at:desc';
    loadPage(1);
  }

  function resetFilters() {
    currentKeyword = '';
    currentCategory = '';
    currentStatus = '';
    currentSort = 'updated_at:desc';
    loadPage(1);
  }

  function friendlyErrorMessage(error) {
    const raw = error?.message || '';
    if (!raw || raw === 'Failed to fetch' || raw.includes('NetworkError')) {
      return '无法连接后端服务，请确认服务已启动后重试。';
    }
    return raw;
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
      await API.ingestDocument(docId, 'incremental');
      UI.toast('已触发重新处理', 'success');
    } catch (e) {
      UI.toast(`重新处理失败: ${e.message}`, 'error');
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
     编辑文档元数据
     ----------------------------------------------------------------------- */
  async function showEditDialog(docId) {
    try {
      const res = await API.getDocument(docId);
      const doc = res?.data || {};

      let existingCategories = [];
      try {
        const filtersRes = await API.searchFilters();
        existingCategories = (filtersRes?.data?.categories || []).map(c => c.value);
      } catch (e) { /* ignore */ }

      const currentCategory = doc.category || '通用';
      const catOptions = [...new Set(['通用', ...existingCategories, currentCategory])]
        .map(c => `<option value="${UI.escapeHtml(c)}" ${currentCategory === c ? 'selected' : ''}>${UI.escapeHtml(c)}</option>`)
        .join('');

      UI.showModal(
        '编辑文档',
        `
          <div class="form-stack">
            <div id="editDocFormError" class="form-error is-hidden"></div>
            <div>
              <label class="field-label">文档标题 <span>*</span></label>
              <input id="editDocTitle" class="input" style="width: 100%;" value="${UI.escapeHtml(doc.title || '')}" />
            </div>
            <div>
              <label class="field-label">分类 <span>(选择已有或输入新分类)</span></label>
              <select class="select" id="editDocCategorySelect" onchange="Documents.onEditCategorySelect()" style="width: 100%;">
                ${catOptions}
                <option value="__custom__">✚ 新增分类…</option>
              </select>
              <input class="input" type="text" id="editDocCategoryInput" placeholder="输入新分类名称" style="width: 100%; margin-top: var(--space-2); display: none;">
            </div>
          </div>
        `,
        `
          <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
          <button class="btn btn-primary" onclick="Documents.saveEdit('${docId}')">保存修改</button>
        `
      );
    } catch (e) {
      UI.toast(`加载文档失败: ${e.message}`, 'error');
    }
  }

  function onEditCategorySelect() {
    const select = document.getElementById('editDocCategorySelect');
    const input = document.getElementById('editDocCategoryInput');
    if (!select || !input) return;
    if (select.value === '__custom__') {
      input.style.display = 'block';
      input.focus();
    } else {
      input.style.display = 'none';
    }
  }

  async function saveEdit(docId) {
    const title = document.getElementById('editDocTitle')?.value?.trim();
    const categorySelect = document.getElementById('editDocCategorySelect');
    const categoryInput = document.getElementById('editDocCategoryInput');
    const errorEl = document.getElementById('editDocFormError');

    let category = '通用';
    if (categorySelect) {
      if (categorySelect.value === '__custom__') {
        category = categoryInput?.value?.trim() || '通用';
      } else {
        category = categorySelect.value;
      }
    }

    if (!title) {
      if (errorEl) {
        errorEl.textContent = '请输入文档标题。';
        errorEl.classList.remove('is-hidden');
      }
      return;
    }

    try {
      await API.updateDocument(docId, { title, category });
      UI.toast('文档已更新', 'success');
      document.querySelector('.modal-backdrop:last-child')?.remove();
      loadPage(currentPage);
    } catch (e) {
      if (errorEl) {
        errorEl.textContent = e.message || '保存失败';
        errorEl.classList.remove('is-hidden');
      }
      UI.toast(`保存失败: ${e.message}`, 'error');
    }
  }

  /* -----------------------------------------------------------------------
     上传页面（v1 上传并可自动提交入库）
     ----------------------------------------------------------------------- */
  let selectedFiles = [];

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
          <div style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: var(--space-1);">可一次选择多个文件，单个文件最大 100 MB，支持 Markdown、TXT、DOCX、XLSX、HTML、PDF、PPTX 格式</div>
          <input type="file" id="fileInput" style="display: none;" accept=".md,.txt,.docx,.xlsx,.html,.htm,.pdf,.pptx" multiple>
          <button class="btn btn-primary" onclick="document.getElementById('fileInput').click();event.stopPropagation()" style="margin-top: var(--space-3);">选择文件</button>
          <div style="display: flex; gap: var(--space-1); justify-content: center; margin-top: var(--space-3);">
            <span class="badge-fmt md">MD</span><span class="badge-fmt txt">TXT</span><span class="badge-fmt docx">DOCX</span><span class="badge-fmt xlsx">XLSX</span>
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
            <div id="fileListDisplay" class="upload-file-list"></div>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); margin-top: var(--space-3);">
            <div>
              <label class="field-label">文档标题 <span>(仅单文件可选)</span></label>
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

    selectedFiles = [];
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
      if (e.dataTransfer.files.length > 0) selectFile(e.dataTransfer.files);
    });
    input.addEventListener('change', () => { if (input.files.length > 0) selectFile(input.files); });
  }

  function selectFile(files) {
    const incoming = Array.from(files instanceof FileList ? files : [files]).filter(Boolean);
    const validFiles = [];
    let skipped = 0;
    incoming.forEach((file) => {
      if (file.size > 100 * 1024 * 1024) {
        skipped++;
        return;
      }
      validFiles.push(file);
    });
    if (skipped) UI.toast(`${skipped} 个文件超过 100 MB，已跳过`, 'error');
    if (!validFiles.length) return;

    selectedFiles = validFiles;
    renderSelectedFiles();
  }

  function renderSelectedFiles() {
    document.getElementById('fileInfo').style.display = 'block';
    const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
    const titleInput = document.getElementById('docTitle');
    document.getElementById('fileNameDisplay').textContent = selectedFiles.length === 1
      ? selectedFiles[0].name
      : `已选择 ${selectedFiles.length} 个文件`;
    document.getElementById('fileSizeDisplay').textContent = selectedFiles.length === 1
      ? UI.formatSize(selectedFiles[0].size)
      : `合计 ${UI.formatSize(totalSize)}`;

    if (titleInput) {
      titleInput.disabled = selectedFiles.length > 1;
      titleInput.placeholder = selectedFiles.length > 1 ? '多文件上传时自动使用文件名' : '留空则使用文件名';
      if (selectedFiles.length > 1) titleInput.value = '';
    }

    const listEl = document.getElementById('fileListDisplay');
    if (listEl) {
      listEl.innerHTML = selectedFiles.map((file, index) => `
        <div class="upload-file-item">
          <span class="upload-file-name">${UI.escapeHtml(file.name)}</span>
          <span class="upload-file-size">${UI.formatSize(file.size)}</span>
          <button class="btn btn-sm btn-ghost" onclick="Documents.removeSelectedFile(${index})">移除</button>
        </div>
      `).join('');
    }
  }

  function clearFile() {
    selectedFiles = [];
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('fileInput').value = '';
  }

  function removeSelectedFile(index) {
    selectedFiles.splice(index, 1);
    if (!selectedFiles.length) {
      clearFile();
      return;
    }
    renderSelectedFiles();
  }

  async function doUpload() {
    if (!selectedFiles.length) { UI.toast('请先选择文件', 'error'); return; }
    const title = selectedFiles.length === 1 ? (document.getElementById('docTitle')?.value?.trim() || '') : '';
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
    progressFill.style.width = '0%'; progressText.textContent = `准备上传 ${selectedFiles.length} 个文件…`;

    try {
      let success = 0;
      let duplicate = 0;
      let failed = 0;
      const failedFiles = [];
      let hasIngestJob = false;

      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        progressText.textContent = `正在上传 ${i + 1}/${selectedFiles.length}：${file.name}`;
        const startedPercent = Math.round((i / selectedFiles.length) * 100);
        progressFill.style.width = `${startedPercent}%`;

        try {
          const result = await API.uploadDocument(file, title, category, {
            ingestAfterCreate: true,
            mode: 'incremental',
          });
          const data = result?.data || {};
          if (data.duplicate) duplicate++;
          else success++;
          if (data.ingest_job_id) hasIngestJob = true;
        } catch (e) {
          failed++;
          failedFiles.push(file);
          console.warn(`上传失败: ${file.name}`, e);
        }

        const finishedPercent = Math.round(((i + 1) / selectedFiles.length) * 100);
        progressFill.style.width = `${finishedPercent}%`;
      }

      progressText.textContent = `上传完成：成功 ${success}，重复 ${duplicate}，失败 ${failed}`;
      UI.toast(`上传完成：成功 ${success}，重复 ${duplicate}，失败 ${failed}`, failed ? 'error' : 'success');
      if (failedFiles.length) {
        selectedFiles = failedFiles;
        renderSelectedFiles();
        btn.disabled = false;
        btn.textContent = '↑ 重试失败文件';
        loadPage(currentPage);
        return;
      }
      setTimeout(() => {
        closeUploadModal();
        loadPage(currentPage);
        if (hasIngestJob) App.router.navigate('/ingestion');
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

  return { renderList, showUploadModal, closeUploadModal, onCategorySelect, onEditCategorySelect, doSearch, resetFilters, loadPage, deleteDoc, restoreDoc, ingestDocument, showEditDialog, saveEdit, toggleSelectAll, toggleSelect, batchDelete, selectFile, clearFile, removeSelectedFile, doUpload };
})();
