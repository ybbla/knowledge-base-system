/* ==========================================================================
   仪表盘组件 — 系统概览、统计数据、状态面板（已迁移至 v1 API）
   ========================================================================== */

const Dashboard = (() => {

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘' }]);

    // 使用 v1 健康检查和依赖状态
    let healthOk = false;
    let backendType = '—';
    let depStatuses = {};

    try {
      const [readyRes, depsRes] = await Promise.all([
        API.healthReady(),
        API.healthDependencies(),
      ]);
      healthOk = readyRes?.data?.status === 'ok';
      backendType = depsRes?.data?.dependencies?.backend?.type || '—';
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
          <div class="stat-detail"><span>支持 6 种格式</span></div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⊞</div>
          <div class="stat-label">知识块</div>
          <div class="stat-value">${UI.formatNumber(chunkCount)}</div>
          <div class="stat-detail"><span>语义抽取 + 向量索引</span></div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⌕</div>
          <div class="stat-label">检索模式</div>
          <div class="stat-value stat-value-sm">混合</div>
          <div class="stat-detail"><span>向量 + BM25 + RRF 融合</span></div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⚙</div>
          <div class="stat-label">后端引擎</div>
          <div class="stat-value stat-value-sm">${UI.escapeHtml(backendType)}</div>
          <div class="stat-detail"><span>LLM: 豆包 Seed 2.0 Pro</span></div>
        </div>
      </div>

      <div class="dashboard-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <h3 class="card-title">系统状态</h3>
              <p class="card-subtitle">仅在仪表盘集中展示健康与依赖状态</p>
            </div>
            <span class="badge badge-${healthOk ? 'success' : 'error'}">${healthOk ? '在线' : '异常'}</span>
          </div>
          <div class="status-panel status-panel-compact">
            <div class="status-item">
              <span class="status-item-label">API 服务</span>
              <span class="status-item-value ${healthOk ? 'is-ok' : 'is-error'}">
                ${healthOk ? '在线' : '离线'}
              </span>
            </div>
            ${Object.entries(depStatuses).slice(0, 6).map(([key, dep]) => `
              <div class="status-item">
                <span class="status-item-label">${dep.name || key}</span>
                <span class="status-item-value ${dep.status === 'ok' ? 'is-ok' : dep.status === 'error' ? 'is-error' : ''}">
                  ${dep.status || '—'}
                </span>
              </div>
            `).join('')}
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h3 class="card-title">快速操作</h3></div>
          <div class="quick-actions">
            <button class="btn btn-primary btn-lg" onclick="Documents.showUploadModal()">↑ 上传文档</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/search')">⌕ 搜索知识库</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/documents')">▦ 浏览文档</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/chunks')">⊞ 知识块管理</button>
          </div>
        </div>
      </div>

      <div class="format-strip">
        <div>
          <h3 class="card-title">支持的文档格式</h3>
          <p class="card-subtitle">自动解析、语义抽取与索引</p>
        </div>
        <div class="format-list">
          <span class="badge-fmt md">MD</span>
          <span class="badge-fmt docx">DOCX</span>
          <span class="badge-fmt xlsx">XLSX</span>
          <span class="badge-fmt html">HTML</span>
          <span class="badge-fmt pdf">PDF</span>
          <span class="badge-fmt pptx">PPTX</span>
        </div>
      </div>
    `);
  }

  return { render };
})();
