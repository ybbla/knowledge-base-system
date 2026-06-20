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
      { path: '/',             icon: '▤', label: '仪表盘' },
      { path: '/documents',    icon: '▦', label: '文档管理' },
      { path: '/chunks',       icon: '⊞', label: '知识块管理' },
      { path: '/search',       icon: '⌕', label: '知识搜索' },
      { path: '/search-debug', icon: '⚙', label: '检索调试' },
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

  function sourceTypeLabel(sourceType) {
    const map = {
      markdown: 'Markdown',
      md: 'Markdown',
      txt: 'TXT',
      text: 'TXT',
      docx: 'DOCX',
      xlsx: 'XLSX',
      html: 'HTML',
      htm: 'HTML',
      pdf: 'PDF',
      pptx: 'PPTX',
      manual: '手工录入',
      unknown: '未知格式',
    };
    return map[(sourceType || '').toLowerCase()] || sourceType || '未知格式';
  }

  /* -----------------------------------------------------------------------
     知识类型徽章
     ----------------------------------------------------------------------- */
  function ktypeBadge(type) {
    const map = {
      declarative: '陈述型',
      relational: '关系型',
      procedural: '流程型',
    };
    const label = map[type] || type || '未知';
    return `<span class="badge-ktype ${type || ''}">${label}</span>`;
  }

  /* -----------------------------------------------------------------------
     知识类型纯文本标签（用于下拉选项等非徽章场景）
     ----------------------------------------------------------------------- */
  function ktypeLabel(type) {
    const map = {
      declarative: '陈述型',
      relational: '关系型',
      procedural: '流程型',
    };
    return map[type] || type || '未知';
  }

  /* -----------------------------------------------------------------------
     状态徽章
     ----------------------------------------------------------------------- */
  function statusBadge(status) {
    const map = {
      active:    ['success', '活跃'],
      deleted:   ['error', '已删除'],
      failed:    ['error', '失败'],
      processing:['info', '处理中'],
      ready:     ['success', '就绪'],
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

  /* -----------------------------------------------------------------------
     服务状态指示器
     ----------------------------------------------------------------------- */
  const ServiceStatus = {
    timer: null,

    update(status, label) {
      const el = document.getElementById('serviceStatus');
      if (!el) return;
      el.className = `service-status-indicator status-${status}`;
      el.querySelector('.service-status-label').textContent = label;
    },

    async check() {
      try {
        const res = await API.healthLive();
        if (res?.data?.status === 'ok') {
          this.update('ok', '服务在线');
        } else {
          this.update('warning', '状态异常');
        }
      } catch (e) {
        this.update('error', '服务离线');
      }
    },

    startPolling(intervalMs = 10000) {
      this.stopPolling();
      this.check();
      this.timer = setInterval(() => this.check(), intervalMs);
    },

    stopPolling() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
    },
  };

  /* -----------------------------------------------------------------------
     抽屉面板
     ----------------------------------------------------------------------- */
  function showDrawer(title, bodyHtml) {
    const container = document.getElementById('modalContainer');
    const el = document.createElement('div');
    el.className = 'drawer';
    el.innerHTML = `
      <div class="drawer-overlay"></div>
      <div class="drawer-content">
        <div class="drawer-header">
          <h2>${escapeHtml(title)}</h2>
          <button class="btn-close" id="drawerCloseBtn">&times;</button>
        </div>
        <div class="drawer-body">${bodyHtml}</div>
      </div>
    `;
    const close = () => {
      el.querySelector('.drawer-content').style.transform = 'translateX(100%)';
      el.querySelector('.drawer-overlay').style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    };
    el.querySelector('#drawerCloseBtn').addEventListener('click', close);
    el.querySelector('.drawer-overlay').addEventListener('click', close);
    container.appendChild(el);
    return { close, el };
  }

  /* -----------------------------------------------------------------------
     确认对话框
     ----------------------------------------------------------------------- */
  function showConfirm(title, message, confirmLabel = '确认', cancelLabel = '取消') {
    return new Promise((resolve) => {
      showModal(
        title,
        `<p style="color:var(--ink-soft);line-height:1.6">${escapeHtml(message)}</p>`,
        `
          <button class="btn btn-secondary" id="confirmCancelBtn">${escapeHtml(cancelLabel)}</button>
          <button class="btn btn-primary" id="confirmOkBtn">${escapeHtml(confirmLabel)}</button>
        `
      );
      // 绑定事件（需要在DOM渲染后）
      setTimeout(() => {
        document.getElementById('confirmCancelBtn')?.addEventListener('click', () => {
          document.querySelector('.modal-backdrop:last-child')?.remove();
          resolve(false);
        });
        document.getElementById('confirmOkBtn')?.addEventListener('click', () => {
          document.querySelector('.modal-backdrop:last-child')?.remove();
          resolve(true);
        });
      }, 50);
    });
  }

  return {
    toast, showModal, showDrawer, showConfirm, renderSidebar, setBreadcrumb,
    escapeHtml, formatTime, formatSize, formatNumber,
    fmtBadge, sourceTypeLabel, ktypeBadge, ktypeLabel, statusBadge, render,
    ServiceStatus,
  };
})();
