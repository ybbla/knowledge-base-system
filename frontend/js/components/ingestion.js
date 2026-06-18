/* ==========================================================================
   入库任务组件 — 状态监控、失败处理（已迁移至 v1 API）
   ========================================================================== */

const Ingestion = (() => {

  let jobs = [];
  let pollingTimer = null;
  let jobStatusFilter = '';
  let jobModeFilter = '';
  let jobKeywordFilter = '';
  let jobTotal = 0;
  let loadError = '';

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
          </div>
        </div>
      </div>

      <div class="doc-toolbar kb-filter-bar ingestion-filter-bar">
        <input class="input kb-toolbar-search" type="text" id="jobKeywordFilter" placeholder="搜索任务 ID / 文档标题…" value="${UI.escapeHtml(jobKeywordFilter)}"
               onkeydown="if(event.key==='Enter')Ingestion.applyFilters()">
        <select class="select select-sm" id="jobStatusFilter" onchange="Ingestion.applyFilters()">
          <option value="">全部状态</option>
          <option value="accepted" ${jobStatusFilter === 'accepted' ? 'selected' : ''}>已接收</option>
          <option value="pending" ${jobStatusFilter === 'pending' ? 'selected' : ''}>待处理</option>
          <option value="processing" ${jobStatusFilter === 'processing' ? 'selected' : ''}>处理中</option>
          <option value="completed" ${jobStatusFilter === 'completed' ? 'selected' : ''}>已完成</option>
          <option value="failed" ${jobStatusFilter === 'failed' ? 'selected' : ''}>失败</option>
          <option value="canceled" ${jobStatusFilter === 'canceled' ? 'selected' : ''}>已取消</option>
        </select>
        <select class="select select-sm" id="jobModeFilter" onchange="Ingestion.applyFilters()">
          <option value="">全部方式</option>
          <option value="incremental" ${jobModeFilter === 'incremental' ? 'selected' : ''}>增量处理</option>
          <option value="force" ${jobModeFilter === 'force' ? 'selected' : ''}>完整处理</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="Ingestion.clearFilters()">清空筛选</button>
        ${jobs.some(j => j.status === 'failed') ? '<button class="btn btn-secondary btn-sm" onclick="Ingestion.retryAllFailed()">重试全部失败</button>' : ''}
        <span class="doc-count" id="jobCountText">显示最近任务</span>
      </div>

      <div class="card pipeline-card ingestion-overview">
        <div>
          <h3 class="card-title">入库管道</h3>
          <p class="inline-note">这里展示服务端当前可见的入库任务，可按状态筛选并处理失败或待执行任务。</p>
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

    try {
      const res = await API.listIngestJobs({
        page_size: 50,
        status: jobStatusFilter || undefined,
        mode: jobModeFilter || undefined,
        keyword: jobKeywordFilter || undefined,
      });
      jobs = res?.data || [];
      jobTotal = res?.meta?.total ?? jobs.length;
      loadError = '';
    } catch (e) {
      jobs = [];
      jobTotal = 0;
      loadError = e.message || '入库任务加载失败';
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
    const countEl = document.getElementById('jobCountText');
    if (countEl) countEl.textContent = loadError ? '任务暂不可用' : `共 ${jobTotal} 个任务`;

    if (loadError) {
      jobListEl.innerHTML = `
        <div class="empty-state empty-state-error">
          <div class="empty-state-icon">!</div>
          <div class="empty-state-title">入库任务加载失败</div>
          <div class="empty-state-desc">${UI.escapeHtml(loadError)}</div>
          <div class="empty-actions">
            <button class="btn btn-primary" onclick="Ingestion.refresh()">重新加载</button>
          </div>
        </div>`;
      return;
    }

    if (jobs.length === 0) {
      const filtered = Boolean(jobStatusFilter || jobModeFilter || jobKeywordFilter);
      jobListEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">↻</div>
          <div class="empty-state-title">${filtered ? '未找到匹配任务' : '暂无入库任务'}</div>
          <div class="empty-state-desc">${filtered ? '当前状态下没有入库任务。可以清空筛选后查看全部任务。' : '上传文档后会自动创建入库任务，可在这里查看解析与索引进度。'}</div>
          <div class="empty-actions">
            ${filtered ? '<button class="btn btn-secondary" onclick="Ingestion.clearStatusFilter()">清空筛选</button>' : ''}
            <button class="btn btn-primary" onclick="Documents.showUploadModal()">上传文档</button>
          </div>
        </div>`;
      return;
    }

    jobListEl.innerHTML = `<div class="job-list">${jobs.map(job => renderJobCard(job)).join('')}</div>`;
  }

  function formatDuration(startedAt, completedAt) {
    if (!startedAt || !completedAt) return '';
    const start = new Date(startedAt);
    const end = new Date(completedAt);
    const secs = Math.floor((end - start) / 1000);
    if (secs < 60) return `${secs}s`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    return `${h}h ${m}m`;
  }

  function renderJobCard(job) {
    const docCount = job.doc_count || job.doc_ids?.length || 0;
    const chunkCount = job.chunk_count ?? '—';
    const assetCount = job.asset_count ?? '—';
    const error = job.error || '';
    const startedAt = job.started_at;
    const completedAt = job.finished_at || job.completed_at;
    const progress = job.progress ?? (['completed', 'failed', 'canceled'].includes(job.status) ? 100 : 0);
    const duration = formatDuration(startedAt, completedAt);
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
        ${job.status === 'processing' ? `<div class="job-progress"><div class="job-progress-bar" style="width: ${progress}%;"></div></div>` : ''}
        <div class="job-stats">
          <div class="job-stat"><span class="job-stat-value">${docCount}</span><span class="job-stat-label">文档数</span></div>
          <div class="job-stat"><span class="job-stat-value">${chunkCount}</span><span class="job-stat-label">知识块</span></div>
          <div class="job-stat"><span class="job-stat-value">${assetCount}</span><span class="job-stat-label">资源</span></div>
          ${job.mode ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${ingestModeLabel(job.mode)}</span><span class="job-stat-label">处理方式</span></div>` : ''}
          ${startedAt ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${UI.formatTime(startedAt)}</span><span class="job-stat-label">开始时间</span></div>` : ''}
          ${completedAt ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${UI.formatTime(completedAt)}</span><span class="job-stat-label">完成时间</span></div>` : ''}
          ${duration ? `<div class="job-stat"><span class="job-stat-value" style="font-size: var(--text-sm);">${duration}</span><span class="job-stat-label">耗时</span></div>` : ''}
        </div>
        ${error ? `<div class="job-error">⚠ ${UI.escapeHtml(error)}</div>` : ''}
        <div class="job-actions">
          ${primaryDocId ? `<button class="btn btn-sm btn-ghost" onclick="App.router.navigate('/documents/${primaryDocPath}')">查看文档</button>` : ''}
          ${job.status === 'failed' ? `<button class="btn btn-sm btn-secondary" onclick="Ingestion.retryJob('${UI.escapeHtml(job.job_id)}')">重试</button>` : ''}
          ${job.status === 'pending' ? `<button class="btn btn-sm btn-danger" onclick="Ingestion.cancelJob('${UI.escapeHtml(job.job_id)}')">取消</button>` : ''}
        </div>
      </div>
    `;
  }

  function ingestModeLabel(mode) {
    if (mode === 'force') return '完整入库流程';
    if (mode === 'incremental') return '更新并替换旧索引';
    return mode || '—';
  }

  function setStatusFilter(value) {
    jobStatusFilter = value || '';
    refresh();
  }

  function applyFilters() {
    jobKeywordFilter = document.getElementById('jobKeywordFilter')?.value?.trim() || '';
    jobStatusFilter = document.getElementById('jobStatusFilter')?.value || '';
    jobModeFilter = document.getElementById('jobModeFilter')?.value || '';
    refresh();
  }

  function clearStatusFilter() {
    clearFilters();
  }

  function clearFilters() {
    jobStatusFilter = '';
    jobModeFilter = '';
    jobKeywordFilter = '';
    const input = document.getElementById('jobKeywordFilter');
    const select = document.getElementById('jobStatusFilter');
    const modeSelect = document.getElementById('jobModeFilter');
    if (input) input.value = '';
    if (select) select.value = '';
    if (modeSelect) modeSelect.value = '';
    refresh();
  }

  async function retryJob(jobId) {
    try {
      await API.retryIngestJob(jobId);
      UI.toast('已重新提交入库任务', 'success');
      await refresh();
    } catch (e) {
      UI.toast(`重试失败: ${e.message}`, 'error');
    }
  }

  async function cancelJob(jobId) {
    try {
      await API.cancelIngestJob(jobId);
      UI.toast('任务已取消', 'success');
      await refresh();
    } catch (e) {
      UI.toast(`取消失败: ${e.message}`, 'error');
    }
  }

  async function retryAllFailed() {
    const failedJobs = jobs.filter(j => j.status === 'failed');
    if (failedJobs.length === 0) {
      UI.toast('没有失败的任务', 'info');
      return;
    }

    let success = 0;
    let failed = 0;

    for (const job of failedJobs) {
      try {
        await API.retryIngestJob(job.job_id);
        success++;
      } catch (e) {
        failed++;
      }
    }

    if (success > 0) {
      UI.toast(`已重试 ${success} 个任务${failed > 0 ? `，${failed} 个失败` : ''}`, success === failedJobs.length ? 'success' : 'warning');
    } else {
      UI.toast('全部重试失败', 'error');
    }

    await refresh();
  }

  return {
    render, refresh, setStatusFilter, applyFilters, clearStatusFilter, clearFilters, retryJob, cancelJob, retryAllFailed,
  };
})();
