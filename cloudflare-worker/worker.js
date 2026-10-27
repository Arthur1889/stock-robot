export default {
  // 1. 定时触发 (Cloudflare Cron Triggers)
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerGitHubAction(env));
  },

  // 2. HTTP 访问触发 (方便在浏览器或控制台点"Run / Test"直接测试)
  async fetch(request, env, ctx) {
    const result = await triggerGitHubAction(env);
    return new Response(JSON.stringify(result, null, 2), {
      status: result.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  },
};

async function triggerGitHubAction(env) {
  if (!env.GH_PAT) {
    const errorMsg = "缺少环境变量 GH_PAT，请在 Cloudflare Workers 后台 Settings -> Variables 中添加 GitHub Personal Access Token。";
    console.error(errorMsg);
    return { ok: false, status: 500, error: errorMsg };
  }

  const owner = "Arthur1889";
  const repo = "stock-robot";
  const workflowFileName = "daily_run.yml";
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFileName}/dispatches`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": `Bearer ${env.GH_PAT}`,
        "User-Agent": "Cloudflare-Worker-Stock-Robot",
      },
      body: JSON.stringify({
        ref: "main"
      }),
    });

    if (res.status === 204) {
      console.log("Successfully triggered GitHub Actions workflow!");
      return {
        ok: true,
        status: 200,
        message: "成功触发 GitHub Actions 工作流！通常在 10~20 秒内开始运行。"
      };
    } else {
      const errText = await res.text();
      console.error(`GitHub API 响应异常: ${res.status} - ${errText}`);
      return {
        ok: false,
        status: res.status,
        error: `GitHub API 报错: HTTP ${res.status}`,
        details: errText
      };
    }
  } catch (err) {
    console.error("网络请求异常:", err);
    return { ok: false, status: 500, error: err.message };
  }
}
