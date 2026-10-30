# WeChat article extraction (`mp.weixin.qq.com`)

Three quirks that used to need manual intervention are handled in code. This
note records what the plugin does so an agent does not re-solve them by hand.

## Automatic curl fallback

When the Node.js extractor fails on `mp.weixin.qq.com`, the plugin falls back to
a curl-based parser: it fetches the HTML, reads the body from `js_content`,
converts it to Markdown and returns the same article shape as the extractor.
No manual step and no second code path in the skill.

## Author field: two-page generations

- Older pages: `var nickname = "..."`.
- Newer pages: `var nickname = htmlDecode("...")`.

The parser tries the plain form first, then the `htmlDecode` form, so both
generations produce a correct `author`. A missing author on a WeChat clip means
both patterns failed — check whether the page changed shape again before
patching anything.

## CAPTCHA wall

WeChat serves a slider CAPTCHA to headless browsers. The curl fallback never
opens a browser, so it bypasses the wall entirely. Do **not** "fix" a WeChat
failure by retrying with the browser: that path hits the CAPTCHA and produces a
different, less useful failure.

## Failure judgement

If both the extractor and the curl fallback fail, report the article as
unavailable for automated clipping. Do not save a partial note whose body is
empty or boilerplate.

## Related References

- `anti-bot-fallback-web-extract.md` — generic `web_extract` fallback when a
  site blocks every automated fetch path
- `batch-processing.md` — WeChat notes inside a multi-article batch
