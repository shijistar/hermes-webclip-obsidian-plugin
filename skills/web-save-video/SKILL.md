---
name: web-save-video
description: Download web videos to local disk; HLS/mp4 via ffmpeg; 下载视频 保存视频 视频下载
version: 1.0.2
author: Hermes Agent / Fengbao Li
metadata:
  hermes:
    tags: [video, download, hls, m3u8, ffmpeg, media, netease]
    related_skills: [web-clip-to-obsidian]
---

# Save Web Video

Turn a video *page* into local mp4 files with `/save-video`. This is the
`webclip-obsidian` plugin's second command; clipping an article is a different
job (`webclip-obsidian:web-clip-to-obsidian`) with different storage rules.

## When to Use

- The user shares a video page (or an article embedding video) and wants the file
- Triggers: 下载这个视频 / 保存视频 / save this video / download the clip
- Not for archiving article text — that is `/webclip`

## One Command

```
/save-video <url> [<url> ...] [--name <name>] [--to <dir>] [--overwrite] [--no-browser]
```

| Flag | Effect |
| --- | --- |
| `<url> ...` | Up to 10 pages per command; each page may hold several videos |
| `--name` | Base filename; with several videos each gets `-1`, `-2` |
| `--to` | Destination directory for this run (overrides `[video].destination`) |
| `--overwrite` | Replace an existing file instead of adding `-1` |
| `--no-browser` | Static fetch only; skips the Playwright fallback |

Every video is reported separately and one failure does not stop the others.
The receipt ends with `MEDIA:` lines for files ≤ 50 MB; larger files stay on disk.

## What It Refuses

Reported as a failure, never as a silent zero:

- **Encrypted HLS** (`EXT-X-KEY`, method ≠ `NONE`) — DRM and AES-128 both stop here
- **Live streams** (no `EXT-X-ENDLIST`) — only what elapsed would be captured
- **Private / link-local / non-default-port addresses** — the page chose the URL,
  so it is resolved once, every answer must be public, and the connection is
  pinned to that address
- **Files over `[video].max_size_mb`** (default 500 MB), checked while writing
- **Pages with no discoverable player** — says so instead of returning nothing

## Where Files Go

Default `[video].destination` is `~/Movies/Videos/webclip`, outside the vault. A
destination inside the vault gets a managed `.gitignore` block that is written
**and committed**, because `/webclip` refuses to run on a dirty worktree. See
`references/storage-policy.md`.

## When It Fails

| Symptom | Read |
| --- | --- |
| No video found on a page that clearly has one | `references/discovery-dom.md` |
| Netease page returns nothing | `references/netease.md` |
| "encrypted", "live stream", "no segments" | `references/download-hls.md` |
| "blocked by network policy", 403/404 while downloading | `references/download-direct.md` |
| Wrong or surprising filename | `references/naming-and-batch.md` |
| Vault dirty / `/webclip` refuses to run | `references/storage-policy.md` |
| Platform support question | `references/platform-matrix.md` |

## Support Files

`platform-matrix` (sites, detection, planned work), `discovery-dom` (how players
are found), `download-hls` (pre-flight and local remux), `download-direct`
(plain files, limits, redirects), `naming-and-batch`, `storage-policy`, and
`netease` (page shapes and measured quirks) — all under `references/`.

Before reporting success, confirm the path exists, its size matches the report,
and a vault destination left `git status` clean.
