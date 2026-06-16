/* ==========================================================================
   入库任务组件 — 任务提交、状态监控、管道可视化
   ========================================================================== */

const Ingestion = (() => {

  let jobs = [];
  let pollingTimer = null;

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '入库任务' }]);

    UI.render(`
      <div class="page-header">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3);">
          <div>
            <h1 class="page-title">入库任务</h1>
            <p class="page-subtitle">管理文档入库任务，监控解析与索引进度</p>
          </div>
          <div style="display: flex; gap: var(--space-2);">
            <button class="btn btn-secondary btn-sm" onclick="Ingestion.refresh()">⟳ 刷新</button>
            <button class="btn btn-primary btn-sm" onclick="Ingestion.showSubmitModal()">+ 新建入库</button>
          </div>
        </div>
      </div>

      <!-- 管道说明 -->
      <div class="card" style="margin-bottom: var(--space-6);">
        <h3 class="card-title" style="margin-bottom: var(--space-3);">入库管道</h3>
        <div class="pipeline-stages" style="flex-wrap: wrap;">
          <span class="pipeline-stage done">① 上传</span>
          <span class="pipeline-arrow">→</span>
          <span class="pipeline-stage done">② 解析</span>
          <span class="pipeline-arrow">→</span>
          <span class="pipeline-stage done">③ 语义抽取</span>
          <span class="pipeline-arrow">→</span>
          <span class="pipeline-stage done">④ 向量嵌入</span>
          <span class="pipeline-arrow">→</span>
          <span class="pipeline-stage done">⑤ 建立索引</span>
        </div>
        <p style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: var(--space-3);">
          文档上传后依次经过：格式解析 → LLM 语义抽取 → Embedding 向量化 → 向量/全文双路索引
        </p>
      </div>

      <!-- 任务列表 -->
      <div id="jobList">
        <div class="loading-overlay">
          <div class="loading-spinner"></div>
          <span>加载入库任务…</span>
        </div>
      </div>
    `);

    await refresh();
  }

  async function refresh() {
    // 停止之前的轮询
    if (pollingTimer) {
      clearTimeout(pollingTimer);
      pollingTimer = null;
    }

    const jobListEl = document.getElementById('jobList');
    if (!jobListEl) return;

    // 从 localStorage 读取提交过的 job ID
    try {
      const storedIds = JSON.parse(localStorage.getItem('kb_job_ids') || '[]');
      const results = await Promise.allSettled(
        storedIds.map(id => API.getIngestJob(id))
      );
      jobs = results
        .filter(r => r.status === 'fulfilled')
        .map(r => r.value)
        .filter(Boolean);

      // 清理不存在的任务
      const validIds = jobs.map(j => j.job_id);
      localStorage.setItem('kb_job_ids', JSON.stringify(validIds));
    } catch (e) {
      jobs = [];
    }

    renderJobList();

    // 如果有未完成的任务，自动轮询
    const hasActive = jobs.some(j =>
      j.status === 'pending' || j.status === 'processing' || j.status === 'accepted'
    );
    if (hasActive) {
      pollingTimer = setTimeout(refresh, 3000);
    }
  }

  function renderJobList() {
    const jobListEl = document.getElementById('jobList');
    if (!jobListEl) return;

    if (jobs.length === 0) {
      jobListEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">↻</div>
          <div class="empty-state-title">暂无入库任务</div>
          <div class="empty-state-desc">
            上传文档后将自动提交入库任务，或点击「新建入库」手动提交已上传的文档。
          </div>
          <button class="btn btn-primary" onclick="App.router.navigate('/upload')" style="margin-top: var(--space-4);">
            ↑ 上传文档
          </button>
        </div>`;
      return;
    }

    jobListEl.innerHTML = `
      <div class="job-list">
        ${jobs.map(job => renderJobCard(job)).join('')}
      </div>`;
  }

  function renderJobCard(job) {
    const docCount = job.doc_count || job.doc_ids?.length || 0;
    const chunkCount = job.chunk_count ?? '—';
    const assetCount = job.asset_count ?? '—';
    const error = job.error || '';
    const startedAt = job.started_at;
    const completedAt = job.completed_at;

    return `
      <div class="job-card">
        <div class="job-card-header">
          <div>
            <span class="job-id">${UI.escapeHtml(job.job_id || '—')}</span>
          </div>
          <div style="display: flex; gap: var(--space-2); align-items: center;">
            ${UI.statusBadge(job.status || 'unknown')}
            ${job.status === 'pending' || job.status === 'processing' ? '<div class="loading-spinner" style="width: 16px; height: 16px;"></div>' : ''}
          </div>
        </div>

        <div class="job-stats">
          <div class="job-stat">
            <span class="job-stat-value">${docCount}</span>
            <span class="job-stat-label">文档数</span>
          </div>
          <div class="job-stat">
            <span class="job-stat-value">${chunkCount}</span>
            <span class="job-stat-label">知识块</span>
          </div>
          <div class="job-stat">
            <span class="job-stat-value">${assetCount}</span>
            <span class="job-stat-label">资源</span>
          </div>
          ${startedAt ? `
          <div class="job-stat">
            <span class="job-stat-value" style="font-size: var(--text-sm);">${UI.formatTime(startedAt)}</span>
            <span class="job-stat-label">开始时间</span>
          </div>` : ''}
          ${completedAt ? `
          <div class="job-stat">
            <span class="job-stat-value" style="font-size: var(--text-sm);">${UI.formatTime(completedAt)}</span>
            <span class="job-stat-label">完成时间</span>
          </div>` : ''}
        </div>

        ${error ? `
          <div style="margin-top: var(--space-3); padding: var(--space-3); background: var(--cinnabar-pale); border-radius: var(--radius-md); font-size: var(--text-xs); color: var(--cinnabar);">
            ⚠ ${UI.escapeHtml(error)}
          </div>` : ''}

        ${job.warnings?.length ? `
          <div style="margin-top: var(--space-2); font-size: var(--text-xs); color: var(--ink-wash);">
            ${job.warnings.map(w => `⚠ ${UI.escapeHtml(w)}`).join('<br>')}
          </div>` : ''}
      </div>
    `;
  }

  /**
   * 提交入库任务模态框
   */
  function showSubmitModal() {
    UI.showModal(
      '新建入库任务',
      `
        <div style="display: flex; flex-direction: column; gap: var(--space-4);">
          <div>
            <label style="font-size: var(--text-xs); color: var(--ink-wash); display: block; margin-bottom: var(--space-1);">
              文档 source_uri
            </label>
            <input class="input" type="text" id="ingestUri" placeholder="file:///path/to/document.md" style="width: 100%;">
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3);">
            <div>
              <label style="font-size: var(--text-xs); color: var(--ink-wash); display: block; margin-bottom: var(--space-1);">
                标题
              </label>
              <input class="input" type="text" id="ingestTitle" placeholder="文档标题" style="width: 100%;">
            </div>
            <div>
              <label style="font-size: var(--text-xs); color: var(--ink-wash); display: block; margin-bottom: var(--space-1);">
                分类
              </label>
              <input class="input" type="text" id="ingestCategory" placeholder="通用" value="通用" style="width: 100%;">
            </div>
          </div>
          <div>
            <label style="font-size: var(--text-xs); color: var(--ink-wash); display: block; margin-bottom: var(--space-1);">
              文档类型
            </label>
            <select class="select" id="ingestType" style="width: 100%;">
              <option value="markdown">Markdown</option>
              <option value="docx">DOCX</option>
              <option value="xlsx">XLSX</option>
              <option value="html">HTML</option>
              <option value="pdf">PDF</option>
              <option value="pptx">PPTX</option>
            </select>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
        <button class="btn btn-primary" onclick="Ingestion.submitNewJob()">提交入库</button>
      `
    );
  }

  async function submitNewJob() {
    const uri = document.getElementById('ingestUri')?.value?.trim();
    const title = document.getElementById('ingestTitle')?.value?.trim();
    const category = document.getElementById('ingestCategory')?.value?.trim() || '通用';
    const sourceType = document.getElementById('ingestType')?.value || 'markdown';

    if (!uri) {
      UI.toast('请输入文档路径', 'error');
      return;
    }

    try {
      const result = await API.submitIngest([{
        title: title || uri.split('/').pop() || '未命名文档',
        source_type: sourceType,
        source_uri: uri,
        category: category,
      }]);

      // 关闭模态框
      document.querySelector('.modal-backdrop')?.remove();

      // 保存 job ID
      if (result?.job_id) {
        const storedIds = JSON.parse(localStorage.getItem('kb_job_ids') || '[]');
        if (!storedIds.includes(result.job_id)) {
          storedIds.push(result.job_id);
          localStorage.setItem('kb_job_ids', JSON.stringify(storedIds));
        }
      }

      UI.toast(`入库任务已提交: ${result?.job_id || 'OK'}`, 'success');
      await refresh();
    } catch (e) {
      UI.toast(`提交失败: ${e.message}`, 'error');
    }
  }

  return { render, refresh, showSubmitModal, submitNewJob };
})();
