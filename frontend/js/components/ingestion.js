/* ==========================================================================
   入库任务组件 — 任务提交、状态监控（已迁移至 v1 API）
   ========================================================================== */

const Ingestion = (() => {

  let jobs = [];
  let pollingTimer = null;
  let submitDocuments = [];
  let submitCategories = [];
  let previousIngestCategory = '通用';

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '入库任务' }]);

    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">入库任务</h1>
            <p class="page-subtitle">管理文档入库任务，监控解析与索引进度</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-secondary btn-sm" onclick="Ingestion.refresh()">⟳ 刷新</button>
            <button class="btn btn-primary btn-sm" onclick="Ingestion.showSubmitModal()">+ 新建入库</button>
          </div>
        </div>
      </div>

      <div class="card pipeline-card ingestion-overview">
        <div>
          <h3 class="card-title">入库管道</h3>
          <p class="inline-note">这里展示的是提交到本浏览器追踪过的入库任务；清除浏览器缓存后，本地任务记录会被清空。</p>
        </div>
        <div class="pipeline-stages">
          <span class="pipeline-stage">上传/登记</span><span class="pipeline-arrow">→</span>
          <span class="pipeline-stage">解析</span><span class="pipeline-arrow">→</span>
          <span class="pipeline-stage">语义抽取</span><span class="pipeline-arrow">→</span>
          <span class="pipeline-stage">向量嵌入</span><span class="pipeline-arrow">→</span>
          <span class="pipeline-stage">建立索引</span>
        </div>
      </div>

      <div id="jobList"><div class="loading-overlay"><div class="loading-spinner"></div><span>加载入库任务…</span></div></div>
    `);

    await refresh();
  }

  async function refresh() {
    if (pollingTimer) { clearTimeout(pollingTimer); pollingTimer = null; }

    const jobListEl = document.getElementById('jobList');
    if (!jobListEl) return;

    // 从 localStorage 读取提交过的 job ID，通过旧接口查询状态
    try {
      const storedIds = JSON.parse(localStorage.getItem('kb_job_ids') || '[]');
      const results = await Promise.allSettled(
        storedIds.map(id => API.getIngestJob(id))
      );
      jobs = results.filter(r => r.status === 'fulfilled').map(r => r.value).filter(Boolean);

      const validIds = jobs.map(j => j.job_id);
      localStorage.setItem('kb_job_ids', JSON.stringify(validIds));
    } catch (e) {
      jobs = [];
    }

    renderJobList();

    const hasActive = jobs.some(j =>
      j.status === 'pending' || j.status === 'processing' || j.status === 'accepted'
    );
    if (hasActive) { pollingTimer = setTimeout(refresh, 3000); }
  }

  function renderJobList() {
    const jobListEl = document.getElementById('jobList');
    if (!jobListEl) return;

    if (jobs.length === 0) {
      jobListEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">↻</div>
          <div class="empty-state-title">暂无入库任务</div>
          <div class="empty-state-desc">可以上传新文档，也可以对已有文档重新触发解析与索引。</div>
          <div class="empty-actions">
            <button class="btn btn-primary" onclick="Ingestion.showSubmitModal()">+ 新建入库</button>
            <button class="btn btn-secondary" onclick="Documents.showUploadModal()">上传文档</button>
          </div>
        </div>`;
      return;
    }

    jobListEl.innerHTML = `<div class="job-list">${jobs.map(job => renderJobCard(job)).join('')}</div>`;
  }

  function renderJobCard(job) {
    const docCount = job.doc_count || job.doc_ids?.length || 0;
    const chunkCount = job.chunk_count ?? '—';
    const assetCount = job.asset_count ?? '—';
    const error = job.error || '';
    const startedAt = job.started_at;
    const completedAt = job.finished_at || job.completed_at;
    const primaryDocId = job.doc_id || job.doc_ids?.[0] || '';
    const primaryDocPath = encodeURIComponent(primaryDocId);

    return `
      <div class="job-card">
        <div class="job-card-header">
          <div>
            <span class="job-id">${UI.escapeHtml(job.job_id || '—')}</span>
            ${primaryDocId ? `<div class="job-doc-ref">文档：${UI.escapeHtml(job.doc_title || primaryDocId)}</div>` : ''}
          </div>
          <div style="display: flex; gap: var(--space-2); align-items: center;">
            ${UI.statusBadge(job.status || 'unknown')}
            ${job.status === 'pending' || job.status === 'processing' ? '<div class="loading-spinner" style="width: 16px; height: 16px;"></div>' : ''}
          </div>
        </div>
        <div class="job-stats">
          <div class="job-stat"><span class="job-stat-value">${docCount}</span><span class="job-stat-label">文档数</span></div>
          <div class="job-stat"><span class="job-stat-value">${chunkCount}</span><span class="job-stat-label">知识块</span></div>
          <div class="job-stat"><span class="job-stat-value">${assetCount}</span><span class="job-stat-label">资源</span></div>
          ${job.mode ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${job.mode === 'force' ? '强制重建' : '增量入库'}</span><span class="job-stat-label">模式</span></div>` : ''}
          ${startedAt ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${UI.formatTime(startedAt)}</span><span class="job-stat-label">开始时间</span></div>` : ''}
          ${completedAt ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${UI.formatTime(completedAt)}</span><span class="job-stat-label">完成时间</span></div>` : ''}
        </div>
        ${error ? `<div class="job-error">⚠ ${UI.escapeHtml(error)}</div>` : ''}
        ${primaryDocId ? `<div class="job-actions"><button class="btn btn-sm btn-ghost" onclick="App.router.navigate('/documents/${primaryDocPath}')">查看文档</button></div>` : ''}
      </div>
    `;
  }

  async function showSubmitModal() {
    submitDocuments = [];
    submitCategories = [];
    let docLoadError = '';
    try {
      const docsRes = await API.listDocuments({ page_size: 200, status: 'active' });
      submitDocuments = docsRes?.data || [];
    } catch (e) {
      docLoadError = e.message || '文档列表加载失败';
    }

    try {
      const filterRes = await API.searchFilters();
      submitCategories = ['通用', ...((filterRes?.data?.categories || []).map(normalizeFilterValue).filter(Boolean))]
        .filter((value, index, arr) => arr.indexOf(value) === index);
    } catch (e) {
      submitCategories = ['通用'];
    }
    previousIngestCategory = submitCategories[0] || '通用';

    const docOptions = submitDocuments.map((doc) => `
      <option value="${UI.escapeHtml(doc.doc_id)}">${UI.escapeHtml(doc.title || doc.doc_id)} · ${UI.escapeHtml(doc.doc_id)}</option>
    `).join('');
    const categoryOptions = submitCategories.map((category) => `
      <option value="${UI.escapeHtml(category)}">${UI.escapeHtml(category)}</option>
    `).join('');

    UI.showModal(
      '新建入库任务',
      `
        <div class="form-stack ingestion-submit-form">
          <div id="ingestFormError" class="form-error is-hidden"></div>

          <div>
            <label class="field-label">入库来源 <span>*</span></label>
            <div class="mode-switch ingestion-mode-switch">
              <label>
                <input type="radio" name="ingestSubmitMode" value="existing" checked onchange="Ingestion.onSubmitModeChange()">
                <span>已有文档入库</span>
              </label>
              <label>
                <input type="radio" name="ingestSubmitMode" value="uri" onchange="Ingestion.onSubmitModeChange()">
                <span>从 URI 创建并入库</span>
              </label>
            </div>
          </div>

          <div id="existingIngestPanel" class="form-stack">
            <div>
              <label class="field-label">选择文档 <span>*</span></label>
              <select class="select" id="ingestDocId" style="width: 100%;" ${docLoadError ? 'disabled' : ''}>
                <option value="">${docLoadError ? '文档列表加载失败' : '选择一个已入库文档'}</option>
                ${docOptions}
              </select>
              <div class="${docLoadError ? 'field-warning' : 'field-help'}">
                ${docLoadError ? `${UI.escapeHtml(docLoadError)}。仍可切换到 URI 模式创建新文档。` : '对已有文档重新执行解析、知识块生成和索引。'}
              </div>
            </div>
            <div>
              <label class="field-label">入库模式</label>
              <select class="select" id="ingestMode" style="width: 100%;">
                <option value="incremental">增量入库：只处理变化内容</option>
                <option value="force">强制重建：重新解析并覆盖索引</option>
              </select>
            </div>
          </div>

          <div id="uriIngestPanel" class="form-stack is-hidden">
            <div>
              <label class="field-label">source_uri <span>*</span></label>
              <input class="input" type="text" id="ingestUri" placeholder="file:///path/to/document.md" style="width: 100%;" oninput="Ingestion.onIngestUriInput()">
              <div class="field-help">支持后端可访问的 file://、http(s):// 或存储 URI。</div>
            </div>
            <div class="form-grid">
              <div>
                <label class="field-label">标题</label>
                <input class="input" type="text" id="ingestTitle" placeholder="留空则使用 URI 文件名" style="width: 100%;">
              </div>
              <div>
                <label class="field-label">分类 <span>(选择已有或新增)</span></label>
                <select class="select" id="ingestCategorySelect" onchange="Ingestion.onIngestCategorySelect()" style="width: 100%;">
                  ${categoryOptions}
                  <option value="__custom__">+ 新增分类...</option>
                </select>
              </div>
            </div>
            <div>
              <label class="field-label">文档类型</label>
              <select class="select" id="ingestType" style="width: 100%;">
                <option value="markdown">Markdown</option>
                <option value="txt">TXT</option>
                <option value="docx">DOCX</option>
                <option value="xlsx">XLSX</option>
                <option value="html">HTML</option>
                <option value="pdf">PDF</option>
                <option value="pptx">PPTX</option>
              </select>
              <div class="field-help">输入 URI 后会根据扩展名自动识别，可手动修正。</div>
            </div>
          </div>

          <div id="ingestCategoryDialog" class="mini-dialog-backdrop is-hidden" role="dialog" aria-modal="true" aria-labelledby="ingestCategoryDialogTitle">
            <div class="mini-dialog">
              <div class="mini-dialog-header">
                <h3 id="ingestCategoryDialogTitle">新增文档分类</h3>
                <button type="button" class="btn-close" onclick="Ingestion.cancelIngestCategory()">&times;</button>
              </div>
              <div class="mini-dialog-body">
                <label class="field-label">分类名称</label>
                <input id="ingestCategoryDialogInput" class="input" style="width: 100%;" placeholder="例如：售后政策"
                       onkeydown="if(event.key==='Enter')Ingestion.confirmIngestCategory();if(event.key==='Escape')Ingestion.cancelIngestCategory();">
                <div id="ingestCategoryDialogError" class="field-warning is-hidden">请输入分类名称。</div>
              </div>
              <div class="mini-dialog-footer">
                <button type="button" class="btn btn-secondary btn-sm" onclick="Ingestion.cancelIngestCategory()">取消</button>
                <button type="button" class="btn btn-primary btn-sm" onclick="Ingestion.confirmIngestCategory()">确认</button>
              </div>
            </div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
        <button class="btn btn-primary" id="submitIngestBtn" onclick="Ingestion.submitNewJob()">提交入库</button>
      `
    );
    setTimeout(() => {
      onSubmitModeChange();
      ['ingestDocId', 'ingestUri', 'ingestTitle', 'ingestCategorySelect'].forEach((id) => {
        document.getElementById(id)?.addEventListener('input', updateSubmitState);
        document.getElementById(id)?.addEventListener('change', updateSubmitState);
      });
      updateSubmitState();
    }, 50);
  }

  async function submitNewJob() {
    const submitMode = getSubmitMode();
    const docId = document.getElementById('ingestDocId')?.value?.trim();
    const uri = document.getElementById('ingestUri')?.value?.trim();
    const mode = document.getElementById('ingestMode')?.value || 'incremental';
    const error = validateSubmitForm(submitMode, docId, uri);
    if (error) {
      showSubmitError(error);
      return;
    }

    const btn = document.getElementById('submitIngestBtn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '提交中...';
    }
    try {
      let jobId = '';
      if (submitMode === 'existing') {
        const res = await API.ingestDocument(docId, mode);
        jobId = res?.data?.job_id || '';
        UI.toast(`已对文档 ${docId} 触发入库`, 'success');
      } else {
        const title = document.getElementById('ingestTitle')?.value?.trim();
        const category = getIngestCategory();
        const sourceType = document.getElementById('ingestType')?.value || 'markdown';

        const docRes = await API.createDocument({
          title: title || uri.split('/').pop() || '未命名文档',
          source_type: sourceType,
          source_uri: uri,
          category: category,
          ingest_after_create: true,
        });
        jobId = docRes?.data?.ingest_job_id || '';
        UI.toast('已创建文档并提交入库', 'success');
      }

      rememberJobId(jobId);
      document.querySelector('.modal-backdrop')?.remove();
      await refresh();
    } catch (e) {
      showSubmitError(e.message || '提交失败');
      UI.toast(`提交失败: ${e.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '提交入库';
      }
    }
  }

  function getSubmitMode() {
    return document.querySelector('input[name="ingestSubmitMode"]:checked')?.value || 'existing';
  }

  function onSubmitModeChange() {
    const mode = getSubmitMode();
    document.getElementById('existingIngestPanel')?.classList.toggle('is-hidden', mode !== 'existing');
    document.getElementById('uriIngestPanel')?.classList.toggle('is-hidden', mode !== 'uri');
    updateSubmitState();
  }

  function validateSubmitForm(mode, docId, uri) {
    if (mode === 'existing' && !docId) return '请选择要入库的文档。';
    if (mode === 'uri' && !uri) return '请输入 source_uri。';
    if (mode === 'uri' && !getIngestCategory()) return '请选择或新增文档分类。';
    return '';
  }

  function showSubmitError(message) {
    const el = document.getElementById('ingestFormError');
    if (!el) return;
    el.textContent = message;
    el.classList.remove('is-hidden');
  }

  function updateSubmitState() {
    const mode = getSubmitMode();
    const docId = document.getElementById('ingestDocId')?.value?.trim();
    const uri = document.getElementById('ingestUri')?.value?.trim();
    const btn = document.getElementById('submitIngestBtn');
    const error = document.getElementById('ingestFormError');
    if (btn && !btn.textContent.includes('提交中')) {
      btn.disabled = Boolean(validateSubmitForm(mode, docId, uri));
    }
    if (error) error.classList.add('is-hidden');
  }

  function onIngestUriInput() {
    const uri = document.getElementById('ingestUri')?.value?.trim() || '';
    const type = inferSourceType(uri);
    const typeSelect = document.getElementById('ingestType');
    if (typeSelect && type) typeSelect.value = type;
    updateSubmitState();
  }

  function inferSourceType(uri) {
    const clean = uri.split('?')[0].split('#')[0].toLowerCase();
    const ext = clean.includes('.') ? clean.split('.').pop() : '';
    const map = { md: 'markdown', markdown: 'markdown', txt: 'txt', docx: 'docx', xlsx: 'xlsx', html: 'html', htm: 'html', pdf: 'pdf', pptx: 'pptx' };
    return map[ext] || '';
  }

  function normalizeFilterValue(item) {
    if (typeof item === 'string') return item;
    return item?.value || item?.label || '';
  }

  function getIngestCategory() {
    const select = document.getElementById('ingestCategorySelect');
    return select?.value?.trim() || '通用';
  }

  function onIngestCategorySelect() {
    const select = document.getElementById('ingestCategorySelect');
    if (!select) return;
    if (select.value === '__custom__') {
      select.value = previousIngestCategory;
      showIngestCategoryDialog();
      return;
    }
    previousIngestCategory = select.value || '通用';
    updateSubmitState();
  }

  function showIngestCategoryDialog() {
    const dialog = document.getElementById('ingestCategoryDialog');
    const input = document.getElementById('ingestCategoryDialogInput');
    const error = document.getElementById('ingestCategoryDialogError');
    if (!dialog || !input) return;
    input.value = '';
    if (error) error.classList.add('is-hidden');
    dialog.classList.remove('is-hidden');
    setTimeout(() => input.focus(), 0);
  }

  function cancelIngestCategory() {
    const dialog = document.getElementById('ingestCategoryDialog');
    const select = document.getElementById('ingestCategorySelect');
    if (dialog) dialog.classList.add('is-hidden');
    if (select) select.value = previousIngestCategory;
    updateSubmitState();
  }

  function confirmIngestCategory() {
    const select = document.getElementById('ingestCategorySelect');
    const input = document.getElementById('ingestCategoryDialogInput');
    const error = document.getElementById('ingestCategoryDialogError');
    if (!select || !input) return;
    const value = input.value.trim();
    if (!value) {
      if (error) error.classList.remove('is-hidden');
      input.focus();
      return;
    }
    if (![...select.options].some(option => option.value === value)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.insertBefore(option, select.querySelector('option[value="__custom__"]'));
    }
    select.value = value;
    previousIngestCategory = value;
    cancelIngestCategory();
  }

  function rememberJobId(jobId) {
    if (!jobId) return;
    const storedIds = JSON.parse(localStorage.getItem('kb_job_ids') || '[]');
    if (!storedIds.includes(jobId)) {
      storedIds.unshift(jobId);
      localStorage.setItem('kb_job_ids', JSON.stringify(storedIds.slice(0, 50)));
    }
  }

  return {
    render, refresh, showSubmitModal, submitNewJob,
    onSubmitModeChange, onIngestUriInput, onIngestCategorySelect,
    cancelIngestCategory, confirmIngestCategory,
  };
})();
