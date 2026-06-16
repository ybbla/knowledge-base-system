/* ==========================================================================
   文档管理组件 — 文档列表、上传、文档详情
   ========================================================================== */

const Documents = (() => {

  let docs = [];
  let filteredDocs = [];
  let page = 1;
  const pageSize = 15;

  async function renderList() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '文档管理' }]);

    // 加载文档列表
    UI.render(`<div class="loading-overlay"><div class="loading-spinner"></div><span>加载文档列表…</span></div>`);

    try {
      const result = await API.listDocuments();
      docs = Array.isArray(result) ? result : (result?.documents || []);
      filteredDocs = [...docs];
    } catch (e) {
      docs = [];
      filteredDocs = [];
      UI.toast(`加载文档失败: ${e.message}`, 'error');
    }

    renderDocListHtml();
  }

  function renderDocListHtml() {
    const totalPages = Math.ceil(filteredDocs.length / pageSize) || 1;
    const start = (page - 1) * pageSize;
    const pageItems = filteredDocs.slice(start, start + pageSize);

    let rowsHtml = '';
    if (pageItems.length === 0) {
      rowsHtml = `
        <tr>
          <td colspan="5">
            <div class="empty-state">
              <div class="empty-state-icon">📭</div>
              <div class="empty-state-title">暂无文档</div>
              <div class="empty-state-desc">
                点击右上角「上传文档」按钮，将您的文档导入知识库。支持 Markdown、DOCX、XLSX、HTML、PDF、PPTX 等格式。
              </div>
              <button class="btn btn-primary" onclick="App.router.navigate('/upload')" style="margin-top: var(--space-4);">
                ↑ 上传第一篇文档
              </button>
            </div>
          </td>
        </tr>`;
    } else {
      rowsHtml = pageItems.map(doc => `
        <tr>
          <td>
            <div class="doc-title-cell">
              ${UI.fmtBadge(doc.source_type)}
              <span class="doc-title-link" onclick="App.router.navigate('/documents/${UI.escapeHtml(doc.doc_id || doc.id)}')">
                ${UI.escapeHtml(doc.title || doc.file_name || '未命名文档')}
              </span>
            </div>
          </td>
          <td>${UI.escapeHtml(doc.category || '通用')}</td>
          <td>${UI.statusBadge(doc.status || 'active')}</td>
          <td>${UI.formatTime(doc.created_at)}</td>
          <td>
            <button class="btn btn-sm btn-ghost" onclick="App.router.navigate('/documents/${UI.escapeHtml(doc.doc_id || doc.id)}')">
              查看 →
            </button>
          </td>
        </tr>
      `).join('');
    }

    UI.render(`
      <div class="page-header">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-3);">
          <div>
            <h1 class="page-title">文档管理</h1>
            <p class="page-subtitle">管理已入库的文档，查看解析结果和知识块</p>
          </div>
          <button class="btn btn-primary" onclick="App.router.navigate('/upload')">↑ 上传文档</button>
        </div>
      </div>

      <!-- 搜索过滤 -->
      <div class="doc-toolbar">
        <input class="input" type="text" id="docSearchInput" placeholder="搜索文档标题…"
               oninput="Documents.filter()">
        <select class="select" id="docStatusFilter" onchange="Documents.filter()">
          <option value="">全部状态</option>
          <option value="active">活跃</option>
          <option value="processing">处理中</option>
          <option value="failed">失败</option>
        </select>
        <span class="doc-count">共 ${filteredDocs.length} 篇文档</span>
      </div>

      <!-- 文档表格 -->
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width: 40%;">文档名称</th>
              <th style="width: 12%;">分类</th>
              <th style="width: 12%;">状态</th>
              <th style="width: 20%;">创建时间</th>
              <th style="width: 10%;">操作</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>

      <!-- 分页 -->
      ${totalPages > 1 ? `
      <div class="pagination">
        <button class="btn btn-sm btn-secondary" onclick="Documents.goPage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>‹ 上一页</button>
        <span class="pagination-info">${page} / ${totalPages}</span>
        <button class="btn btn-sm btn-secondary" onclick="Documents.goPage(${page + 1})" ${page >= totalPages ? 'disabled' : ''}>下一页 ›</button>
      </div>` : ''}
    `);
  }

  /* -----------------------------------------------------------------------
     过滤
     ----------------------------------------------------------------------- */
  function filter() {
    const searchInput = document.getElementById('docSearchInput');
    const statusFilter = document.getElementById('docStatusFilter');
    const query = (searchInput?.value || '').toLowerCase();
    const status = statusFilter?.value || '';

    filteredDocs = docs.filter(doc => {
      const title = (doc.title || doc.file_name || '').toLowerCase();
      const matchQuery = !query || title.includes(query);
      const matchStatus = !status || doc.status === status;
      return matchQuery && matchStatus;
    });
    page = 1;
    renderDocListHtml();
  }

  function goPage(n) {
    const totalPages = Math.ceil(filteredDocs.length / pageSize) || 1;
    if (n < 1 || n > totalPages) return;
    page = n;
    renderDocListHtml();
    document.getElementById('content').scrollIntoView({ behavior: 'smooth' });
  }

  /* -----------------------------------------------------------------------
     上传页面
     ----------------------------------------------------------------------- */
  function renderUpload() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '文档管理', path: '#/documents' }, { label: '上传文档' }]);

    UI.render(`
      <div class="page-header">
        <h1 class="page-title">上传文档</h1>
        <p class="page-subtitle">将文档导入知识库，系统将自动解析、抽取知识并建立索引</p>
      </div>

      <div style="max-width: 600px;">
        <!-- 上传区域 -->
        <div class="upload-zone" id="uploadZone">
          <span class="upload-zone-icon">📁</span>
          <div class="upload-zone-title">拖拽文件到此处，或点击选择</div>
          <div class="upload-zone-desc">
            单个文件最大 100 MB，支持 Markdown、DOCX、XLSX、HTML、PDF、PPTX 格式
          </div>
          <input type="file" id="fileInput" style="display: none;"
                 accept=".md,.txt,.docx,.xlsx,.html,.htm,.pdf,.pptx">
          <button class="btn btn-primary" onclick="document.getElementById('fileInput').click()">
            选择文件
          </button>
          <div class="upload-formats">
            <span class="badge-fmt md">MD</span>
            <span class="badge-fmt docx">DOCX</span>
            <span class="badge-fmt xlsx">XLSX</span>
            <span class="badge-fmt html">HTML</span>
            <span class="badge-fmt pdf">PDF</span>
            <span class="badge-fmt pptx">PPTX</span>
          </div>
        </div>

        <!-- 文件信息 -->
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

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); margin-top: var(--space-4);">
            <div>
              <label style="font-size: var(--text-xs); color: var(--ink-wash); display: block; margin-bottom: var(--space-1);">
                文档标题 <span style="color: var(--ink-wash-light);">(可选)</span>
              </label>
              <input class="input" type="text" id="docTitle" placeholder="留空则使用文件名"
                     style="width: 100%;">
            </div>
            <div>
              <label style="font-size: var(--text-xs); color: var(--ink-wash); display: block; margin-bottom: var(--space-1);">
                分类
              </label>
              <input class="input" type="text" id="docCategory" placeholder="通用" value="通用"
                     style="width: 100%;">
            </div>
          </div>

          <button class="btn btn-primary btn-lg" id="uploadBtn" onclick="Documents.doUpload()"
                  style="width: 100%; margin-top: var(--space-4); justify-content: center;">
            ↑ 开始上传并入库
          </button>

          <div id="uploadProgress" style="display: none; margin-top: var(--space-4);">
            <div class="upload-progress-bar">
              <div class="upload-progress-fill" id="uploadProgressFill" style="width: 0%;"></div>
            </div>
            <div class="upload-progress-text" id="uploadProgressText">上传中…</div>
          </div>
        </div>
      </div>
    `);

    // 绑定拖拽上传事件
    setTimeout(() => bindUploadEvents(), 50);
  }

  function bindUploadEvents() {
    const zone = document.getElementById('uploadZone');
    const input = document.getElementById('fileInput');
    if (!zone || !input) return;

    zone.addEventListener('click', () => input.click());

    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('drag-over');
    });

    zone.addEventListener('dragleave', () => {
      zone.classList.remove('drag-over');
    });

    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const files = e.dataTransfer.files;
      if (files.length > 0) selectFile(files[0]);
    });

    input.addEventListener('change', () => {
      if (input.files.length > 0) selectFile(input.files[0]);
    });
  }

  let selectedFile = null;

  function selectFile(file) {
    // 检查大小
    const maxSize = 100 * 1024 * 1024; // 100 MB
    if (file.size > maxSize) {
      UI.toast('文件大小超过 100 MB 限制', 'error');
      return;
    }

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
    if (!selectedFile) {
      UI.toast('请先选择文件', 'error');
      return;
    }

    const title = document.getElementById('docTitle')?.value?.trim() || '';
    const category = document.getElementById('docCategory')?.value?.trim() || '通用';
    const btn = document.getElementById('uploadBtn');
    const progressDiv = document.getElementById('uploadProgress');
    const progressFill = document.getElementById('uploadProgressFill');
    const progressText = document.getElementById('uploadProgressText');

    btn.disabled = true;
    btn.textContent = '上传中…';
    progressDiv.style.display = 'block';
    progressFill.style.width = '30%';
    progressText.textContent = '正在上传文件…';

    try {
      const result = await API.uploadFile(selectedFile, title, category);
      progressFill.style.width = '60%';
      progressText.textContent = '上传完成，正在提交入库…';

      // 自动提交入库任务
      const ingestResult = await API.submitIngest([{
        title: title || selectedFile.name,
        source_type: detectSourceType(selectedFile.name),
        source_uri: result.source_uri,
        category: category,
      }]);

      progressFill.style.width = '100%';
      progressText.textContent = '入库任务已提交！';

      UI.toast(`文档 "${title || selectedFile.name}" 已上传并提交入库`, 'success');

      // 延迟跳转到入库任务页面
      setTimeout(() => {
        App.router.navigate('/ingestion');
      }, 1500);
    } catch (e) {
      progressText.textContent = `失败: ${e.message}`;
      UI.toast(`上传失败: ${e.message}`, 'error');
      btn.disabled = false;
      btn.textContent = '↑ 重试上传';
    }
  }

  function detectSourceType(filename) {
    const ext = (filename || '').split('.').pop()?.toLowerCase();
    const map = {
      md: 'markdown', txt: 'text',
      docx: 'docx', xlsx: 'xlsx',
      html: 'html', htm: 'html',
      pdf: 'pdf', pptx: 'pptx',
    };
    return map[ext] || 'unknown';
  }

  return { renderList, renderUpload, filter, goPage, selectFile, clearFile, doUpload };
})();
