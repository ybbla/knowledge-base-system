/* ==========================================================================
   通用组件 — Toast、Modal、侧边栏、面包屑、格式化工具
   ========================================================================== */

const UI = (() => {

  /* -----------------------------------------------------------------------
     Toast 消息
     ----------------------------------------------------------------------- */
  function toast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `
      <span>${escapeHtml(message)}</span>
      <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(el);

    if (duration > 0) {
      setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(16px)';
        el.style.transition = 'all 200ms ease-out';
        setTimeout(() => el.remove(), 200);
      }, duration);
    }
  }

  /* -----------------------------------------------------------------------
     模态框
     ----------------------------------------------------------------------- */
  function showModal(title, bodyHtml, footerHtml = '') {
    const container = document.getElementById('modalContainer');
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h2 class="modal-title">${escapeHtml(title)}</h2>
          <button class="modal-close" id="modalCloseBtn">&times;</button>
        </div>
        <div class="modal-body">${bodyHtml}</div>
        ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
      </div>
    `;

    const close = () => {
      backdrop.style.opacity = '0';
      backdrop.style.transition = 'opacity 200ms ease-out';
      setTimeout(() => backdrop.remove(), 200);
    };

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close();
    });
    backdrop.querySelector('#modalCloseBtn')?.addEventListener('click', close);

    container.appendChild(backdrop);
    return { close, backdrop };
  }

  /* -----------------------------------------------------------------------
     侧边栏渲染
     ----------------------------------------------------------------------- */
  function renderSidebar(currentPath) {
    const nav = document.getElementById('sidebarNav');

    const items = [
      { path: '/',            icon: '▤', label: '仪表盘' },
      { path: '/documents',   icon: '▦', label: '文档管理' },
      { path: '/search',      icon: '⌕', label: '知识搜索' },
      { path: '/ingestion',   icon: '↻', label: '入库任务' },
    ];

    nav.innerHTML = items.map(item => `
      <a class="nav-item${currentPath === item.path ? ' active' : ''}"
         href="#${item.path}"
         data-path="${item.path}">
        <span class="nav-icon">${item.icon}</span>
        <span>${item.label}</span>
      </a>
    `).join('');
  }

  /* -----------------------------------------------------------------------
     面包屑
     ----------------------------------------------------------------------- */
  function setBreadcrumb(parts) {
    const el = document.getElementById('breadcrumb');
    el.innerHTML = parts.map((p, i) =>
      i < parts.length - 1
        ? `<a href="${p.path || '#'}">${escapeHtml(p.label)}</a> › `
        : `<span>${escapeHtml(p.label)}</span>`
    ).join('');
  }

  /* -----------------------------------------------------------------------
     状态指示器
     ----------------------------------------------------------------------- */
  function setBackendStatus(ok, backend = '') {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    if (ok) {
      dot.className = 'status-dot';
      text.textContent = backend || '服务正常';
    } else {
      dot.className = 'status-dot error';
      text.textContent = '服务离线';
    }
  }

  /* -----------------------------------------------------------------------
     HTML 转义
     ----------------------------------------------------------------------- */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /* -----------------------------------------------------------------------
     时间格式化
     ----------------------------------------------------------------------- */
  function formatTime(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${y}-${mo}-${day} ${h}:${mi}`;
  }

  function formatSize(bytes) {
    if (bytes == null) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  function formatNumber(n) {
    if (n == null) return '0';
    if (n >= 10000) return `${(n / 10000).toFixed(1)} 万`;
    return n.toLocaleString('zh-CN');
  }

  /* -----------------------------------------------------------------------
     文档格式徽章
     ----------------------------------------------------------------------- */
  function fmtBadge(sourceType) {
    const t = (sourceType || '').toLowerCase();
    const map = {
      markdown: 'md', md: 'md', txt: 'txt', text: 'txt',
      docx: 'docx', xlsx: 'xlsx', html: 'html', htm: 'html',
      pdf: 'pdf', pptx: 'pptx',
    };
    const cls = map[t] || 'txt';
    const label = cls.toUpperCase();
    return `<span class="badge-fmt ${cls}">${label}</span>`;
  }

  /* -----------------------------------------------------------------------
     知识类型徽章
     ----------------------------------------------------------------------- */
  function ktypeBadge(type) {
    const map = {
      declarative: '陈述性',
      relational: '关系性',
      procedural: '过程性',
    };
    const label = map[type] || type || '未知';
    return `<span class="badge-ktype ${type || ''}">${label}</span>`;
  }

  /* -----------------------------------------------------------------------
     状态徽章
     ----------------------------------------------------------------------- */
  function statusBadge(status) {
    const map = {
      active:    ['success', '活跃'],
      deleted:   ['error', '已删除'],
      failed:    ['error', '失败'],
      pending:   ['warning', '等待中'],
      processing:['info', '处理中'],
      indexed:   ['success', '已索引'],
      ready:     ['success', '就绪'],
      superseded:['neutral', '已替代'],
    };
    const [cls, label] = map[status] || ['neutral', status || '未知'];
    return `<span class="badge badge-${cls}">${label}</span>`;
  }

  /* -----------------------------------------------------------------------
     快捷渲染到 #content
     ----------------------------------------------------------------------- */
  function render(html) {
    document.getElementById('content').innerHTML = html;
  }

  return {
    toast, showModal, renderSidebar, setBreadcrumb, setBackendStatus,
    escapeHtml, formatTime, formatSize, formatNumber,
    fmtBadge, ktypeBadge, statusBadge, render,
  };
})();
