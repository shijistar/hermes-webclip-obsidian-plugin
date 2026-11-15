"""Site-specific fallbacks: WeChat and Netease video."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import urlsplit
import re

from .core import ClipError, MAX_STDERR_BYTES, MAX_STDOUT_BYTES
from .extract import run_extractor
from .proc import _run_bounded

_WECHAT_HOST_RE = re.compile(r"(?:^|\.)weixin\.qq\.com$", re.IGNORECASE)


_NETEASE_HOST_RE = re.compile(r"(?:^|\.)163\.com$", re.IGNORECASE)


_NETEASE_VIDEO_PATH_RE = re.compile(r"/news/(?:sv|v)/", re.IGNORECASE)


_NETEASE_VIDEO_STREAM_RE = re.compile(
    r"(https?://[^\s\"'<>]+\.(?:m3u8|mp4)[^\s\"'<>]*)", re.IGNORECASE
)


_NETEASE_VIDEO_TITLE_RE = re.compile(
    r'<title>([^<]+)</title>', re.IGNORECASE
)


_NETEASE_VIDEO_AUTHOR_RE = re.compile(
    r'"nickname"\s*:\s*"([^"]+)"', re.IGNORECASE
)


_NETEASE_VIDEO_AUTHOR_HTML_RE = re.compile(
    r'class="exhibit-authors-info"[^>]*>.*?class="s-name"[^>]*>([^<]+)</div>',
    re.IGNORECASE | re.DOTALL,
)


_NETEASE_VIDEO_COVER_RE = re.compile(
    r'class="poster[^"]*"[^>]*data-bg="(https?://[^"]+)"', re.IGNORECASE
)


_NETEASE_VIDEO_DATE_RE = re.compile(
    r'(20\d{6})/', re.IGNORECASE
)


_WECHAT_TITLE_RE = re.compile(r"var\s+msg_title\s*=\s*[\"'](.+?)[\"']")


_WECHAT_AUTHOR_RE = re.compile(r"var\s+nickname\s*=\s*[\"'](.+?)[\"']")


_WECHAT_AUTHOR_HTML_DECODE_RE = re.compile(
    r"var\s+nickname\s*=\s*htmlDecode\(\s*[\"'](.+?)[\"']", re.IGNORECASE
)


_WECHAT_TIME_RE = re.compile(r"var\s+ct\s*=\s*[\"']?(\d+)[\"']?")


_WECHAT_BODY_RE = re.compile(
    r"<div[^>]+id=[\"']js_content[\"'][^>]*>(.*?)</div>",
    re.DOTALL | re.IGNORECASE,
)


def _is_wechat_url(url: str) -> bool:
    """Return True when *url* points to a WeChat public-account article."""
    try:
        return bool(_WECHAT_HOST_RE.search(urlsplit(url).hostname or ""))
    except Exception:
        return False


def _is_netease_video_url(url: str) -> bool:
    """Return True when *url* points to a Netease video short link."""
    try:
        parts = urlsplit(url)
        if not _NETEASE_HOST_RE.search(parts.hostname or ""):
            return False
        return bool(_NETEASE_VIDEO_PATH_RE.search(parts.path))
    except Exception:
        return False


def _fetch_netease_video_html(url: str, *, timeout: int = 30) -> str:
    """Fetch the raw HTML of a Netease video page via curl."""
    result = _run_bounded(
        [
            "curl", "-sL", "-f",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "-H", "Accept-Language: zh-CN,zh;q=0.9",
            "--max-time", str(timeout),
            url,
        ],
        timeout=timeout + 5,
        stdout_limit=MAX_STDOUT_BYTES,
        stderr_limit=MAX_STDERR_BYTES,
    )
    if result.returncode != 0:
        raise ClipError("Netease video page fetch failed.")
    html = result.stdout.decode("utf-8", errors="replace")
    if len(html) < 500:
        raise ClipError("Netease video page response is too short.")
    return html


def _parse_netease_video_html(html: str, url: str) -> dict[str, object]:
    """Parse metadata and video stream from a Netease video HTML page."""
    title_m = _NETEASE_VIDEO_TITLE_RE.search(html)
    author_m = _NETEASE_VIDEO_AUTHOR_RE.search(html)
    author_html_m = _NETEASE_VIDEO_AUTHOR_HTML_RE.search(html)
    cover_m = _NETEASE_VIDEO_COVER_RE.search(html)

    title = title_m.group(1).strip() if title_m else ""
    # Prefer JSON nickname; fall back to HTML class="s-name" for video pages.
    author = (author_m.group(1).strip() if author_m else "") or (
        author_html_m.group(1).strip() if author_html_m else ""
    )
    cover_url = cover_m.group(1) if cover_m else ""
    published = ""
    if cover_url:
        date_m = _NETEASE_VIDEO_DATE_RE.search(cover_url)
        if date_m:
            raw_date = date_m.group(1)  # e.g. "20261008"
            published = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

    if not title:
        raise ClipError("Netease video content could not be parsed.")

    # Extract video stream URL (m3u8 or mp4)
    stream_m = _NETEASE_VIDEO_STREAM_RE.search(html)
    stream_url = stream_m.group(1) if stream_m else ""

    # Build markdown with video embed
    markdown_parts = ["## 视频信息\n"]
    markdown_parts.append("| 项目 | 详情 |")
    markdown_parts.append("|------|------|")
    markdown_parts.append(f"| **标题** | {title} |")
    if author:
        markdown_parts.append(f"| **作者** | {author} |")
    if published:
        markdown_parts.append(f"| **发布日期** | {published} |")
    markdown_parts.append("| **来源** | 网易视频 |")
    markdown_parts.append("")

    if cover_url:
        markdown_parts.append(f"![视频封面]({cover_url})\n")

    if stream_url:
        markdown_parts.append("## 观看视频\n")
        markdown_parts.append(
            f'<video src="{stream_url}" controls preload="metadata" playsinline></video>'
        )
        markdown_parts.append("")
    else:
        markdown_parts.append("> ⚠️ 未能提取视频流链接，请通过原链接观看。\n")

    markdown_parts.append(f"[原链接]({url})")

    return {
        "ok": True,
        "title": title,
        "author": author,
        "published": published,
        "description": "",
        "site": "c.m.163.com",
        "canonicalUrl": url,
        "url": url,
        "keywords": [],
        "markdown": "\n".join(markdown_parts),
        "wordCount": _count_words("\n".join(markdown_parts)),
        "method": "netease-video-curl",
    }


def _fetch_wechat_html(url: str, *, timeout: int = 30) -> str:
    """Fetch the raw HTML of a WeChat article via curl."""
    result = _run_bounded(
        [
            "curl",
            "-sL",
            "-H",
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "-H",
            "Accept-Language: zh-CN,zh;q=0.9",
            "--max-time",
            str(timeout),
            url,
        ],
        timeout=timeout + 5,
        stdout_limit=MAX_STDOUT_BYTES,
        stderr_limit=MAX_STDERR_BYTES,
    )
    if result.returncode != 0:
        raise ClipError("WeChat article fetch failed.")
    html = result.stdout.decode("utf-8", errors="replace")
    if len(html) < 500:
        raise ClipError("WeChat article response is too short.")
    return html


def _wechat_html_to_markdown(html: str) -> str:
    """Convert WeChat article body HTML to Markdown."""
    text = html
    # Images: <img data-src="URL"> or <img src="URL">
    text = re.sub(
        r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\'][^>]*/?>',
        r"![\2](\1)",
        text,
        flags=re.IGNORECASE,
    )
    # Images without alt text
    text = re.sub(
        r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\'][^>]*/?>',
        r"![](\1)",
        text,
        flags=re.IGNORECASE,
    )
    # Headings
    for level in range(6, 0, -1):
        prefix = "#" * level
        text = re.sub(
            rf"<h{level}[^>]*>(.*?)</h{level}>",
            rf"\n{prefix} \1\n",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # Bold and italic
    text = re.sub(
        r"<strong[^>]*>(.*?)</strong>",
        r"**\1**",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"<em[^>]*>(.*?)</em>",
        r"*\1*",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Line breaks and paragraphs
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    for old, new in (
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&nbsp;", " "),
    ):
        text = text.replace(old, new)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _count_words(markdown: str) -> int:
    """Count words/tokens in Markdown text (CJK characters counted individually)."""
    return len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]|\w+", markdown, re.UNICODE))


def _parse_wechat_html(html: str, url: str) -> dict[str, object]:
    """Parse metadata and body from a WeChat article HTML page."""
    title_m = _WECHAT_TITLE_RE.search(html)
    author_m = _WECHAT_AUTHOR_RE.search(html)
    author_decode_m = _WECHAT_AUTHOR_HTML_DECODE_RE.search(html)
    time_m = _WECHAT_TIME_RE.search(html)

    title = title_m.group(1) if title_m else ""
    # Older pages write var nickname = "..."; newer ones wrap it in htmlDecode.
    author = (author_m.group(1) if author_m else "") or (
        author_decode_m.group(1) if author_decode_m else ""
    )
    publish_time = ""
    if time_m:
        try:
            publish_time = datetime.fromtimestamp(
                int(time_m.group(1)), tz=timezone.utc
            ).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            pass

    body_m = _WECHAT_BODY_RE.search(html)
    body_html = body_m.group(1) if body_m else ""

    if not title or not body_html:
        raise ClipError("WeChat article content could not be parsed.")

    markdown = _wechat_html_to_markdown(body_html)
    return {
        "ok": True,
        "title": title,
        "author": author,
        "published": publish_time,
        "description": "",
        "site": "mp.weixin.qq.com",
        "canonicalUrl": url,
        "url": url,
        "keywords": [],
        "markdown": markdown,
        "wordCount": _count_words(markdown),
        "method": "wechat-curl",
    }


def run_extractor_with_fallback(
    plugin_root: Path, url: str, no_browser: bool = False
) -> dict[str, object]:
    """Run the Node.js extractor; fall back to curl for WeChat/video URLs on failure."""
    try:
        return run_extractor(plugin_root, url, no_browser=no_browser)
    except ClipError:
        if _is_wechat_url(url):
            html = _fetch_wechat_html(url)
            return _parse_wechat_html(html, url)
        if _is_netease_video_url(url):
            html = _fetch_netease_video_html(url)
            return _parse_netease_video_html(html, url)
        raise
