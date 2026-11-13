# Normalizing pasted input

## Invariant

**`service.run()` must only ever receive a cleaned URL.**

The `webclip_id` is derived from whatever URL reaches the service. A
parameterised URL therefore makes the same article look like a different one:
it gets clipped a second time, and `--favorite` against the existing note stops
matching. Cleaning before the call is what removes that ambiguity — the service
never sees the raw paste.

Clean first, then call. Never pass a raw share-sheet paste through.

## Why cleaning lives here and not in the plugin

App share sheets do two things: they prepend the article title, and they append
tracking parameters. Neither means anything to a clip.

But **every site does it differently**:

- Netease prepends a title *and* appends seven `sps*` parameters.
- Juejin omits the title but still appends `share_token`.
- WeChat's new format (`/s/<id>`) carries no query at all.
- WeChat's legacy format needs `__biz`, `mid`, `idx`, `sn` to resolve an article
  — stripping those breaks it permanently.

One generic "strip all query parameters" rule would destroy the WeChat legacy
form. So the rules are maintained **per site**, and a site that is not listed is
passed through **unchanged**. Guessing is worse than doing nothing: a wrong strip
can make an article unreachable, and it will look like a fetch bug rather than an
input bug.

## The three steps

1. **Drop the title.** Keep the first `http(s)://` URL and discard all other
   text. Handles `title [url](url)`, `title url`, and a lone URL.
2. **Strip that site's tracking keys** from the table below. Remove only the
   listed keys. Leave every other parameter untouched, including ones you do not
   recognise — they may be load-bearing.
3. **Verify** before calling: the path still identifies the same article, and any
   surviving query is either empty or made of functional parameters.

## Site rules

| Site | Host | Paste shape | Strip | Must keep | Verified |
| --- | --- | --- | --- | --- | --- |
| Netease News | `c.m.163.com`, `*.163.com/news/` | `title + [url](url)` | `spss` `spsnuid` `spsdevid` `spsvid` `spsshare` `spsts` `spstoken` | — | ✅ 2026-11-12, 2501 chars, identical after strip |
| Juejin | `juejin.cn` | URL only, no title | `share_token` | — | ✅ 2026-11-12, 2702 chars, identical after strip |
| Zhihu | `zhihu.com`, `zhuanlan.zhihu.com` | `title + url` | `utm_*` `share_code` `utm_psn` | — | ✅ rule confirmed by user |
| Bilibili | `bilibili.com`, `b23.tv` | `title + url` | `spm_id_from` `vd_source` `share_source` `share_medium` `share_plat` `share_tag` `share_times` `bbdown` | `bvid`, `p` | ✅ 2026-11-12, identical after strip |
| WeChat (new) | `mp.weixin.qq.com/s/<id>` | `title + url` | nothing — the form carries no query | entire path | ✅ shape confirmed 2026-11-12 (no parameters exist) |
| WeChat (legacy) | `mp.weixin.qq.com/s?__biz=…` | `title + url` | `chksm` `scene` `subscene` `srcid` `sharer_sharetime` `sharer_shareid` `isappinstalled` `clicktime` `enterid` | **`__biz` `mid` `idx` `sn`** | ⚠️ unverified — needs a live legacy URL |
| *anything else* | — | — | **nothing** | everything | pass through unchanged |

### Netease News

```
before  崔添翼点赞！开源插件让DeepSeek Harness操作Figma画UI做动效 [https://c.m.163.com/news/a/LBH61E890556KHRQ.html?spss=newsapp&spsnuid=mo3v…%3D&spsdevid=CQlj…%253D&spsvid=MjI5…&spsshare=default&spsts=1794530197078&spstoken=VKJz…%3D%3D](https://c.m.163.com/news/a/LBH61E890556KHRQ.html?spss=…)
after   https://c.m.163.com/news/a/LBH61E890556KHRQ.html
```

The paste often contains the same URL twice (the visible text and the link
target). Both collapse to the same cleaned URL, so it counts as one URL.

### Juejin

```
before  https://juejin.cn/post/7705987138957328427?share_token=fb68737b-d220-4d74-94e3-1789831447bb
after   https://juejin.cn/post/7705987138957328427
```

Juejin pastes usually carry no title. Do not invent one; the extractor supplies
the real title.

### Zhihu

```
before  https://zhuanlan.zhihu.com/p/123456789?utm_psn=1700000000000&share_code=abc123
after   https://zhuanlan.zhihu.com/p/123456789
```

Applies to both `zhuanlan.zhihu.com/p/<id>` and
`www.zhihu.com/question/<qid>/answer/<aid>`; only the query is touched.

### Bilibili

```
before  https://www.bilibili.com/video/BV1efWd6CEvF?spm_id_from=333.337.search-card.all.click&vd_source=4f2a…&share_source=copy_web
after   https://www.bilibili.com/video/BV1efWd6CEvF
```

`bvid` lives in the path, not the query, so stripping loses nothing. Keep `p`
when present (multi-part videos): `?p=2` selects the part.

### WeChat

New-style links need no cleaning at all:

```
https://mp.weixin.qq.com/s/Xx83p04jFbqQyNE3hzUuGQ
```

Legacy links must keep their identity parameters:

```
before  https://mp.weixin.qq.com/s?__biz=MzA5xxx==&mid=2650000000&idx=1&sn=abc123&chksm=def456&scene=21#wechat_redirect
after   https://mp.weixin.qq.com/s?__biz=MzA5xxx==&mid=2650000000&idx=1&sn=abc123
```

`chksm` is a signature, `scene` records where the share came from, and the
trailing `#wechat_redirect` is a fragment — none of them identify the article.
`__biz` / `mid` / `idx` / `sn` do: without them the page cannot be resolved.

## Parameters that must never be stripped

| Parameter | Why |
| --- | --- |
| `__biz`, `mid`, `idx`, `sn` | WeChat legacy article identity |
| `?p=` on Bilibili | selects a video part |
| `?id=`, `?aid=`, `?page=` | article or page identity on countless sites |
| any `%XX`-encoded value | decode later if needed; never rewrite here |

When in doubt, keep it. A leftover tracking parameter costs nothing; a removed
identity parameter turns a working article into a 404.

## Sites not in the table

Pass the URL through **unchanged** and clip it. Do not strip "looks like a
tracker" parameters by name — `utm_*` on an unknown host may still be harmless,
but `ref`, `from`, `src` and friends frequently select content.

If a clip from a share sheet fails or produces the wrong article, that is the
signal to add a row to the table — not to loosen the rule for everyone.

## Self-check before calling `service.run()`

- [ ] The argument is a URL, not a title plus a URL.
- [ ] The path is unchanged from the paste.
- [ ] Every remaining query key is either functional or the site is unlisted.
- [ ] No trailing sentence punctuation (`,` `。` `）` `】`) stuck to the URL.
- [ ] `%3D` / `%2F` sequences were left encoded, not decoded.
- [ ] If the paste held the URL twice, only one URL is passed.

## Verification log

| Date | Case | Result |
| --- | --- | --- |
| 2026-11-12 | Netease full share paste | cleaned → `ok: true`, 2501 chars, identical to parameterised fetch |
| 2026-11-12 | Juejin with `share_token` | cleaned → `ok: true`, 2702 chars, identical to parameterised fetch |
| 2026-11-12 | Bilibili with 3 share params | cleaned → `ok: true`, canonical identical |
| 2026-11-12 | WeChat `/s/<id>` | shape has no query to strip (sample article was deleted by its author) |
| 2026-11-12 | Plain URL, no query | passed through byte-for-byte |
