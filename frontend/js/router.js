/* ==========================================================================
   路由 — 基于 hash 的轻量 SPA 路由
   ========================================================================== */

const Router = (() => {
  const routes = {};
  let currentRoute = null;
  let beforeEachGuard = null;

  /**
   * 注册路由
   */
  function on(pattern, handler) {
    routes[pattern] = handler;
  }

  /**
   * 导航守卫
   */
  function beforeEach(fn) {
    beforeEachGuard = fn;
  }

  /**
   * 解析当前 hash
   */
  function resolve() {
    const hash = window.location.hash.slice(1) || '/';
    // 尝试匹配精确路径
    if (routes[hash]) return { handler: routes[hash], params: {} };

    // 尝试匹配带参数路径 (如 /documents/:id)
    for (const [pattern, handler] of Object.entries(routes)) {
      const paramNames = [];
      const regexStr = pattern.replace(/:([^/]+)/g, (_, name) => {
        paramNames.push(name);
        return '([^/]+)';
      });
      const regex = new RegExp(`^${regexStr}$`);
      const match = hash.match(regex);
      if (match) {
        const params = {};
        paramNames.forEach((name, i) => { params[name] = match[i + 1]; });
        return { handler, params };
      }
    }

    return null;
  }

  /**
   * 导航到指定路径
   */
  function navigate(path) {
    window.location.hash = path;
  }

  /**
   * 执行当前路由
   */
  async function run() {
    const resolved = resolve();
    if (!resolved) {
      navigate('/');
      return;
    }

    // 导航守卫
    if (beforeEachGuard) {
      const allowed = await beforeEachGuard(resolved);
      if (allowed === false) return;
    }

    currentRoute = { path: window.location.hash.slice(1) || '/', params: resolved.params };
    await resolved.handler(resolved.params);
  }

  /**
   * 获取当前路由信息
   */
  function current() {
    return currentRoute;
  }

  // 监听 hash 变化
  window.addEventListener('hashchange', run);
  window.addEventListener('DOMContentLoaded', run);

  return { on, navigate, run, current, beforeEach };
})();
