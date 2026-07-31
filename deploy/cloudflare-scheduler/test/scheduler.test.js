import assert from "node:assert/strict";
import { test } from "node:test";
import { triggerWorkflow } from "../src/index.js";

test("triggerWorkflow posts to GitHub workflow dispatch endpoint", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(null, { status: 204 });
  };

  try {
    await triggerWorkflow({
      GITHUB_TOKEN: "test-token",
      GITHUB_OWNER: "GurunathBhandarkavathe",
      GITHUB_REPO: "NewsAgent",
      GITHUB_WORKFLOW_ID: "publish-instagram.yml",
      GITHUB_REF: "main",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    "https://api.github.com/repos/GurunathBhandarkavathe/NewsAgent/actions/workflows/publish-instagram.yml/dispatches",
  );
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers.Authorization, "Bearer test-token");
  assert.equal(calls[0].options.headers["X-GitHub-Api-Version"], "2026-03-10");
  assert.deepEqual(JSON.parse(calls[0].options.body), { ref: "main" });
});

test("triggerWorkflow requires a token", async () => {
  await assert.rejects(
    triggerWorkflow({
      GITHUB_OWNER: "GurunathBhandarkavathe",
      GITHUB_REPO: "NewsAgent",
      GITHUB_WORKFLOW_ID: "publish-instagram.yml",
      GITHUB_REF: "main",
    }),
    /GITHUB_TOKEN/,
  );
});
