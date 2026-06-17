/* ==========================================================================
   App — 应用入口，路由注册与初始化
   ========================================================================== */

const App = (() => {

  /* -----------------------------------------------------------------------
     路由注册
     ----------------------------------------------------------------------- */
  function initRouter() {
    // 仪表盘
    Router.on('/', async () => {
      UI.renderSidebar('/');
      await Dashboard.render();
    });

    // 文档列表
    Router.on('/documents', async () => {
      UI.renderSidebar('/documents');
      await Documents.renderList();
    });

    // 文档详情
    Router.on('/documents/:id', async (params) => {
      UI.renderSidebar('/documents');
      await DocumentDetail.render(params.id);
    });

    // 搜索
    Router.on('/search', async () => {
      UI.renderSidebar('/search');
      await SearchPage.render();
    });

    // 入库任务
    Router.on('/ingestion', async () => {
      UI.renderSidebar('/ingestion');
      await Ingestion.render();
    });

    // ── v1 路由 ──

    // 知识块管理
    Router.on('/chunks', async () => {
      UI.renderSidebar('/chunks');
      await Chunks.render();
    });

    // 检索调试
    Router.on('/search-debug', async () => {
      UI.renderSidebar('/search-debug');
      await SearchPage.renderDebug();
    });

    // 系统状态已集成到仪表盘中，不再作为独立页面
  }

  /* -----------------------------------------------------------------------
     初始化
     ----------------------------------------------------------------------- */
  async function init() {
    initRouter();

    // 移动端菜单切换
    document.getElementById('mobileMenuBtn')?.addEventListener('click', () => {
      document.getElementById('sidebar')?.classList.toggle('open');
    });

    // 点击内容区关闭移动端侧边栏
    document.getElementById('content')?.addEventListener('click', () => {
      document.getElementById('sidebar')?.classList.remove('open');
    });

    // 键盘快捷键: Ctrl+K / Cmd+K 快速跳转搜索
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        Router.navigate('/search');
      }
    });

    // 启动路由
    await Router.run();
  }

  // DOM 加载完成后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return {
    router: Router,
    dashboard: Dashboard,
    documents: Documents,
    documentDetail: DocumentDetail,
    search: SearchPage,
    ingestion: Ingestion,
    ui: UI,
    api: API,
  };
})();
