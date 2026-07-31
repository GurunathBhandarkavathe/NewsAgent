const GITHUB_API_VERSION = "2026-03-10";

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(triggerWorkflow(env, controller));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/health") {
      return new Response("Not found", { status: 404 });
    }
    return Response.json({
      ok: true,
      owner: env.GITHUB_OWNER,
      repo: env.GITHUB_REPO,
      workflow: env.GITHUB_WORKFLOW_ID,
      ref: env.GITHUB_REF,
    });
  },
};

export async function triggerWorkflow(env, controller = {}) {
  const required = ["GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO", "GITHUB_WORKFLOW_ID", "GITHUB_REF"];
  const missing = required.filter((name) => !env[name]);
  if (missing.length > 0) {
    throw new Error(`Missing required environment values: ${missing.join(", ")}`);
  }

  const endpoint = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW_ID}/dispatches`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "samachar-bharat-cloudflare-scheduler",
      "X-GitHub-Api-Version": GITHUB_API_VERSION,
    },
    body: JSON.stringify({ ref: env.GITHUB_REF }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GitHub workflow dispatch failed: ${response.status} ${detail}`);
  }

  console.log(
    JSON.stringify({
      status: "workflow_dispatch_sent",
      cron: controller.cron || null,
      scheduledTime: controller.scheduledTime || null,
      workflow: env.GITHUB_WORKFLOW_ID,
      ref: env.GITHUB_REF,
    }),
  );
}
