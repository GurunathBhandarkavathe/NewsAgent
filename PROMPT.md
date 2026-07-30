# Master Prompt For Building Samachar Bharat NewsAgent

You are implementing Samachar Bharat, a local-first India trending news Instagram carousel agent.

Build a Python app that runs every 3 hours in `Asia/Kolkata`, gathers India-related trending news across politics, films, sports, current affairs, and international, creates one 4-5 slide Instagram carousel draft, writes a 5-10 line neutral Instagram description with clear story context, source courtesies, and links, brands the assets as Samachar Bharat, avoids all publisher/news-channel images by default, and requires human approval before any Instagram publishing.

Core requirements:

- Use secure configuration from `.env`; never commit secrets.
- Support brand config through `BRAND_NAME`, `BRAND_HANDLE`, `BRAND_TAGLINE`, and `BRAND_BIO`.
- Store drafts, stories, statuses, source logs, and dedupe keys in SQLite.
- Use free source adapters for direct publisher RSS feeds, GDELT DOC API, and Google Trends-style RSS.
- Score stories by recency, source count, category balance, India relevance, and image availability.
- Deduplicate the same story for 24-48 hours.
- Render each slide at 1080x1350 with Samachar Bharat branding, category/source label, visible courtesy text, and a clear news-brief sentence below the image instead of a headline-only title.
- Default to `IMAGE_POLICY=branded_cards`, which must not place article, publisher, or news-channel images into slides.
- Keep `IMAGE_POLICY=article_images` only as an explicit opt-in, with rights-risk tracking and approval warnings.
- Generate detailed Instagram descriptions with a per-story block containing title, context, source/courtesy, full-report link, and hashtags.
- Provide approval actions: approve, reject, hold, regenerate description, regenerate image.
- Publish approved drafts through Meta's official Instagram Content Publishing API when credentials and public image hosting are configured.
- If credentials or public image URLs are missing, export a manual posting package instead of failing.
- Log every cycle: selected stories, skipped stories, sources, generated files, approval status, and publish status.

Acceptance tests:

- A mocked dry cycle generates exactly 4-5 slides.
- Category balancing prefers one story per configured category.
- Recent duplicate stories are skipped.
- Instagram descriptions include source names, context, and links.
- Publishing is impossible without explicit approval.
- Missing Meta credentials produce a manual export package.
- Secrets are loaded from environment variables only.
