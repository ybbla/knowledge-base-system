/* ==========================================================================
   仪表盘组件 — 系统概览、统计数据、状态面板
   ========================================================================== */

const Dashboard = (() => {

  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘' }]);

    // 检查后端健康状态
    let healthOk = false;
    let backendInfo = '';
    try {
      const health = await API.healthCheck();
      healthOk = health && health.status === 'ok';
    } catch (e) { /* offline */ }

    UI.setBackendStatus(healthOk, '服务正常');

    // 尝试获取文档列表来统计
    let docs = [];
    let docCount = 0;
    let chunkCount = 0;
    try {
      docs = await API.listDocuments();
      docCount = Array.isArray(docs) ? docs.length : (docs?.total || 0);
    } catch (e) {
      // 文档 API 可能尚未实现，使用占位数据
    }

    UI.render(`
      <div class="page-header">
        <h1 class="page-title">知识库概览</h1>
        <p class="page-subtitle">文档入库、语义抽取、混合检索 — 一站式知识管理</p>
      </div>

      <!-- 统计卡片 -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon">▦</div>
          <div class="stat-label">文档总数</div>
          <div class="stat-value" id="statDocCount">${UI.formatNumber(docCount)}</div>
          <div class="stat-detail">
            <span>📄 支持 6 种格式</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⊞</div>
          <div class="stat-label">知识块</div>
          <div class="stat-value" id="statChunkCount">—</div>
          <div class="stat-detail">
            <span>🔍 语义抽取 + 向量索引</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⌕</div>
          <div class="stat-label">检索模式</div>
          <div class="stat-value" style="font-size: 1.5rem;">混合</div>
          <div class="stat-detail">
            <span>向量 + BM25 + RRF 融合</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⚙</div>
          <div class="stat-label">后端引擎</div>
          <div class="stat-value" id="statBackend" style="font-size: 1.5rem;">—</div>
          <div class="stat-detail">
            <span>LLM: 豆包 Seed 2.0 Pro</span>
          </div>
        </div>
      </div>

      <!-- 系统状态 + 快速操作 -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-6);">
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">系统状态</h3>
          </div>
          <div class="status-panel" style="grid-template-columns: 1fr; margin-bottom: 0;">
            <div class="status-item">
              <span class="status-item-label">API 服务</span>
              <span class="status-item-value" style="color: ${healthOk ? 'var(--jade)' : 'var(--cinnabar)'}">
                ${healthOk ? '● 在线' : '○ 离线'}
              </span>
            </div>
            <div class="status-item">
              <span class="status-item-label">向量检索引擎</span>
              <span class="status-item-value" style="color: var(--ink-wash-light)">—</span>
            </div>
            <div class="status-item">
              <span class="status-item-label">全文检索引擎</span>
              <span class="status-item-value" style="color: var(--ink-wash-light)">—</span>
            </div>
            <div class="status-item">
              <span class="status-item-label">LLM 服务</span>
              <span class="status-item-value" style="color: var(--ink-wash-light)">—</span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h3 class="card-title">快速操作</h3>
          </div>
          <div style="display: flex; flex-direction: column; gap: var(--space-3);">
            <button class="btn btn-primary btn-lg" onclick="App.router.navigate('/upload')" style="justify-content: center;">
              ↑ 上传文档
            </button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/search')" style="justify-content: center;">
              ⌕ 搜索知识库
            </button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/documents')" style="justify-content: center;">
              ▦ 浏览文档
            </button>
          </div>
        </div>
      </div>

      <!-- 支持的文档格式 -->
      <div style="margin-top: var(--space-8);">
        <h3 class="card-title" style="margin-bottom: var(--space-3);">支持的文档格式</h3>
        <div style="display: flex; gap: var(--space-3); flex-wrap: wrap;">
          <span class="badge-fmt md">MD</span>
          <span class="badge-fmt docx">DOCX</span>
          <span class="badge-fmt xlsx">XLSX</span>
          <span class="badge-fmt html">HTML</span>
          <span class="badge-fmt pdf">PDF</span>
          <span class="badge-fmt pptx">PPTX</span>
        </div>
        <p style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: var(--space-3);">
          支持 Markdown、Word、Excel、HTML、PDF、PowerPoint 六种格式的自动解析、语义抽取与索引
        </p>
      </div>
    `);
  }

  return { render };
})();
