// 后端 A1~A15 的 fetch 封装 + 统一错误处理（零依赖）
const API = (() => {
  async function req(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    let data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      const message = data && data.error ? data.error.message : ('HTTP ' + resp.status);
      const code = data && data.error ? data.error.code : ('HTTP_' + resp.status);
      const err = new Error(message);
      err.code = code;
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  return {
    health: () => req('GET', '/api/health'),
    getConfig: () => req('GET', '/api/config'),
    putConfig: (patch) => req('PUT', '/api/config', patch),
    scan: (dir, recursive) => req('POST', '/api/scan', { dir, recursive }),
    portCheck: (port) => req('POST', '/api/port-check', { port }),
    tokenize: (text) => req('POST', '/api/tokenize', { text }),
    preview: (models, config) => req('POST', '/api/tasks/preview', { models, config }),
    createTask: (models, config) => req('POST', '/api/tasks', { models, config }),
    getTask: (id) => req('GET', '/api/tasks/' + id),
    taskPoints: (id) => req('GET', '/api/tasks/' + id + '/points'),
    abortTask: (id) => req('POST', '/api/tasks/' + id + '/abort'),
    listReports: () => req('GET', '/api/reports'),
    buildOverview: (task_id) => req('POST', '/api/reports/overview/build', { task_id }),

    // ---- 面向零基础用户的辅助接口 ----
    pickDir: (title) => req('POST', '/api/dialog/pick-dir', { title: title || '' }),
    pickFile: (title, patterns) =>
      req('POST', '/api/dialog/pick-file', { title: title || '', patterns: patterns || '' }),
    openFolder: (path) => req('POST', '/api/open-folder', { path: path || '' }),
    recommend: () => req('GET', '/api/hardware/recommend'),
    llamaCheck: (path) => req('POST', '/api/llama/check', { path }),
    llamaDownload: (destDir) => req('POST', '/api/llama/download', { dest_dir: destDir || '' }),
    llamaDownloadStatus: () => req('GET', '/api/llama/download/status'),
    hints: () => req('GET', '/api/hints'),
    runnerMode: () => req('GET', '/api/runner-mode')
  };
})();
