# Zhihu Article Extraction

`zhuanlan.zhihu.com` / `www.zhihu.com` articles: which fetch layer to try, what each refusal
means, and how to save a body that only the last layer returned.

Companion to `browser-extraction-ladder.md` (transport and platform split) and
`zhihu-cookie-and-scraper-diagnostics.md` (cookie/login/scraper diagnostics). This file owns the
per-article procedure; those two own diagnostics and transport.

## Climb the ladder, stop at the first layer that returns a body

| # | Layer | Command |
| --- | --- | --- |
| 1 | Bundled extractor, protocol only | `node extractor/src/cli.mjs <url> --no-browser` |
| 2 | Bundled extractor, Playwright | `node extractor/src/cli.mjs <url>` |
| 3 | Logged-in real browser (CDP, or `browser_exec` with `local: true`) | see `browser-extraction-ladder.md` |
| 4 | `web_extract` | `from hermes_tools import web_extract` |

Landing on rung 4 is normal operation on Zhihu, not an incident: rungs 1–2 answer an
unauthenticated request with `403`, and rung 3 is not guaranteed either.

## Read each refusal before choosing the next rung

- `HTTP_STATUS` from the CLI means the server answered with a non-2xx status. The CLI does not
  echo the code back: 403, 404, 429 and 5xx all surface as the same `HTTP_STATUS` with the same
  message, so do not read it as "anti-bot". Probe the status separately
  (`curl -sS -o /dev/null -w '%{http_code}' <url>` with the same user agent) before deciding —
  a 404 is a wrong URL, a 5xx is the site's problem, and only a 403/429 points at throttling.
  Whichever it is, move down the ladder instead of retrying the same rung.
- A logged-in browser whose `document.body.innerText` is bare JSON
  `{"error":{"message":"…请求存在异常…","code":40362}}` with a placeholder `document.title` is
  **request-layer throttling**. It says nothing about the cookies: never report it as "cookies
  invalid" and never ask the user to log in again.

  Prove it in one pass rather than inferring from a single page. In the same browser, in the same
  minute, probe the homepage (it renders 消息/私信 and no 登录/注册, so the session is alive) and
  `/search?q=…` (it returns result links), then the article. Homepage and search serving while
  every `zhuanlan.zhihu.com/p/<id>` answers 40362 localises the throttle to the article route,
  not to the identity. Retest at least two articles that were clipped successfully before — one
  blocked article can be a fluke, two cannot.
- `web_extract` returning a clean Markdown body is success. Save it with
  `anti-bot-fallback-web-extract.md`.
- Report which layer produced the body and which layers were refused. Do not collapse the
  layers into one verdict.

## Login is not an extraction lever

Reading is throttled at the request layer, so a session does not unblock it: expect
`web_extract` to stay the channel with cookies and without them. Login fixes identity, not
access. It matters only for posting, commenting, voting and private streams.

When a session genuinely is required, go through the credential manager, never the keyboard:
`browser_vault(action="list")` for the site handle → open the sign-in page with
`browser_exec(local=True)` → fill the identifier with `fill_input` →
`browser_vault(action="fill", handle=…)` places the password into the page. Never type, request
or repeat a password, SMS or 2FA code, and never drive a sign-in form with `computer_use` — that
is desktop tooling, and typing a password through it breaks the rule outright. Expect a
slider/CAPTCHA at that step; it is the user's to clear.

## Trimming the body

`web_extract` returns the whole rendered page. The article sits between two blocks of chrome;
saving it raw produces a note that looks complete but carries ads and login prompts.

- Cut the head up to the first real content element: the placeholder image pointing back at the
  article URL, the `ZhiHu logo`, share banners.
- Cut the tail from the metadata line `编辑于 <date> <time>・<region>`; it is followed by topic
  links, ad cards, `赞同 N 条评论`, comments, `大家都在搜`, `推荐阅读`, app-download and
  `未注册手机验证后自动登录` blocks.
- Find both boundaries by structure (headings, the `编辑于` line), never by the first text match
  of a noise phrase — those words also occur inside the body.
- Count `![](...)` images **after** trimming; Zhihu articles commonly end at zero.

## Saving a fallback body

Use the recipe in `anti-bot-fallback-web-extract.md` (`_persist_article` with the body in
`content_markdown=`), and build the Git handle with `GitSync.preflight(vault, branch)` rather
than the constructor — preflight validates the sync branch, refuses an in-progress Git
operation and rebases onto upstream. Two Zhihu-specific details:

- Derive `image_mode`/`image_count` from the trimmed body: `n == 0` → `image_mode=None`;
  `n > 0` → `image_mode="remote"`, `image_count=n`. Otherwise the receipt reports "no images"
  while the note carries them.
- A receipt from plugin 0.22.0+ already leads with a `| 标题 |` row; do not prepend another.

## Metadata when the page is blocked

The blocked-page Markdown still carries the page's own metadata blocks:

- author: the display name under `关于作者`, or the `作者` label on the first comment.
- published: the `编辑于 <date>` value — an **edit** timestamp, not necessarily the original
  publish date; say so in the report.
- description: the leading blockquote; `site`: `zhihu.com`.

## Verify before reporting success

Read the note back: frontmatter `title/url/published`, first and last body line, total lines, and
that the bullet counts match the sections kept. If the receipt reports the commit as pushed,
confirm the remote object exists for it
(`gh api repos/<owner>/<repo>/contents/<path>?ref=<branch> --jq '.size'`) —
`commit_state`/`push_state` are the plugin's own report, not proof of the remote write. A
`--no-git` clip has nothing to look up: Git reports `disabled`, no commit is made, and the local
read-back is the entire verification.

## Pitfalls

- **Re-running a refused layer** rarely clears: `40362` is throttling with a cooling-off period.
  Move down the ladder.
- **`--no-browser` is not "the quick attempt"** on Zhihu: it 403s on any article that needs a
  session. Run it only to tell a protocol refusal from a rendering failure.
- **A dirty plugin repo blocks the clip**: the vault/plugin hygiene check refuses to commit over
  unrelated work. Stash it (`git stash push -m <label>`, never discard) and name it in the report.
- **Fallback bodies carry link-shaped headings.** Measured 16 of 73: Zhihu renders tag headings
  as `https://zhida.zhihu.com/search?…&zd_token=…` links, and `web_extract` keeps the anchor.
  They are the page's own DOM, not content drift. Do not flatten them on a fallback note: the
  fallback payload sets `article["markdown"] = ""`, so `source_content_hash` is the constant
  `sha256("\n")` (`sha256:01ba4719…`) and describes nothing. Any rule shaped "source hash
  unchanged ⇒ the page did not change" is vacuously true there, and a rewritten article would be
  saved without the `--refresh` gate. Check the field in one line before building anything on
  it:

  ```python
  clip._frontmatter_from_text(note)["source_content_hash"]   # constant ⇒ no source fingerprint
  ```

  Flattening only becomes safe once the real page text is what feeds `source_content_hash`.
  Until then, link-shaped headings are a reading annoyance; a blind fingerprint is a
  correctness bug.
