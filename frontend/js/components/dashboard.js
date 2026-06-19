/* ==========================================================================
   仪表盘组件 — 系统概览、统计数据、状态面板（已迁移至 v1 API）
   ========================================================================== */

const Dashboard = (() => {

  function _formatStatus(status) {
    if (status === 'ok') return '正常';
    if (status === 'error') return '异常';
    if (status === 'not_configured') return '未配置';
    return status || '—';
  }

  function _getStatusClass(status) {
    if (status === 'ok') return 'is-ok';
    if (status === 'error') return 'is-error';
    return '';
  }

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘' }]);

    // 使用 v1 健康检查和依赖状态
    let healthOk = false;
    let depStatuses = {};
    let activeJobCount = 0;
    let failedJobCount = 0;
    let failedDocCount = 0;
    let failedIndexChunkCount = 0;
    let pendingIndexChunkCount = 0;

    try {
      const [readyRes, depsRes] = await Promise.all([
        API.healthReady(),
        API.healthDependencies(),
      ]);
      healthOk = readyRes?.data?.status === 'ok';
      depStatuses = depsRes?.data?.dependencies || {};
    } catch (e) { /* offline */ }

    // 获取文档统计
    let docCount = 0;
    let chunkCount = 0;
    try {
      const docsRes = await API.listDocuments({ page: 1, page_size: 1 });
      docCount = docsRes?.meta?.total || 0;
    } catch (e) { /* ignore */ }

    try {
      const chunksRes = await API.listChunks({ page: 1, page_size: 1 });
      chunkCount = chunksRes?.meta?.total || 0;
    } catch (e) { /* ignore */ }

    try {
      const [acceptedRes, pendingRes, processingRes, failedRes] = await Promise.all([
        API.listIngestJobs({ page: 1, page_size: 1, status: 'accepted' }),
        API.listIngestJobs({ page: 1, page_size: 1, status: 'pending' }),
        API.listIngestJobs({ page: 1, page_size: 1, status: 'processing' }),
        API.listIngestJobs({ page: 1, page_size: 1, status: 'failed' }),
      ]);
      activeJobCount = (acceptedRes?.meta?.total || 0) + (pendingRes?.meta?.total || 0) + (processingRes?.meta?.total || 0);
      failedJobCount = failedRes?.meta?.total || 0;
    } catch (e) { /* ignore */ }

    try {
      const [failedDocsRes, failedIndexRes, pendingIndexRes] = await Promise.all([
        API.listDocuments({ page: 1, page_size: 1, status: 'failed' }),
        API.listChunks({ page: 1, page_size: 1, index_status: 'failed' }),
        API.listChunks({ page: 1, page_size: 1, index_status: 'pending' }),
      ]);
      failedDocCount = failedDocsRes?.meta?.total || 0;
      failedIndexChunkCount = failedIndexRes?.meta?.total || 0;
      pendingIndexChunkCount = pendingIndexRes?.meta?.total || 0;
    } catch (e) { /* ignore */ }

    // 只显示外部服务
    const externalDeps = [
      depStatuses.postgresql,
      depStatuses.milvus,
      depStatuses.minio,
      depStatuses.llm
    ].filter(Boolean);

    UI.render(`
      <div class="page-header">
        <h1 class="page-title">知识库概览</h1>
        <p class="page-subtitle">文档入库、语义抽取、混合检索 — 一站式知识管理</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon">▦</div>
          <div class="stat-label">文档总数</div>
          <div class="stat-value">${UI.formatNumber(docCount)}</div>
          <div class="stat-detail"><span>支持 7 种格式</span></div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⊞</div>
          <div class="stat-label">知识块</div>
          <div class="stat-value">${UI.formatNumber(chunkCount)}</div>
          <div class="stat-detail"><span>语义抽取 + 向量索引</span></div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⌕</div>
          <div class="stat-label">进行中任务</div>
          <div class="stat-value stat-value-sm">${activeJobCount}</div>
          <div class="stat-detail"><span>${failedJobCount ? `${failedJobCount} 个失败任务待处理` : '暂无失败任务'}</span></div>
        </div>
      </div>

      <div class="dashboard-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <h3 class="card-title">系统状态</h3>
              <p class="card-subtitle">外部服务连接状态</p>
            </div>
            <span class="badge badge-${healthOk ? 'success' : 'error'}">${healthOk ? '在线' : '异常'}</span>
          </div>
          <div class="status-panel">
            <div class="status-item">
              <span class="status-item-label">API 服务</span>
              <span class="status-item-value ${healthOk ? 'is-ok' : 'is-error'}">
                ${healthOk ? '在线' : '离线'}
              </span>
            </div>

            ${externalDeps.length ? `
              <div class="status-group-header">外部服务</div>
              ${externalDeps.map(dep => `
                <div class="status-item">
                  <span class="status-item-label">${dep.name}</span>
                  <span class="status-item-value ${_getStatusClass(dep.status)}">
                    ${_formatStatus(dep.status)}
                  </span>
                </div>
              `).join('')}
            ` : ''}
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h3 class="card-title">快速操作</h3></div>
          <div class="quick-actions">
            <button class="btn btn-primary btn-lg" onclick="Documents.showUploadModal()">↑ 上传文档</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/search')">⌕ 搜索知识</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/documents')">▦ 浏览文档</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/chunks')">⊞ 知识块管理</button>
          </div>
        </div>
      </div>

      <div class="card action-card">
        <div class="card-header">
          <div>
            <h3 class="card-title">待处理事项</h3>
            <p class="card-subtitle">优先处理会影响检索可用性的异常</p>
          </div>
        </div>
        <div class="action-list">
          <button class="action-row" onclick="App.router.navigate('/ingestion')">
            <span>失败入库任务</span>
            <strong>${failedJobCount}</strong>
          </button>
          <button class="action-row" onclick="App.router.navigate('/documents')">
            <span>失败文档</span>
            <strong>${failedDocCount}</strong>
          </button>
          <button class="action-row" onclick="App.router.navigate('/chunks')">
            <span>索引失败知识块</span>
            <strong>${failedIndexChunkCount}</strong>
          </button>
          <button class="action-row" onclick="App.router.navigate('/chunks')">
            <span>待索引知识块</span>
            <strong>${pendingIndexChunkCount}</strong>
          </button>
        </div>
      </div>
    `);
  }

  return { render };
})();
