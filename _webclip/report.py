"""Clip result objects and the summary receipt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit
import re

from .core import ClipError, _SECRET_PATTERNS

# A page <title> may be up to 10 KB; the receipt is printed verbatim, so cap it.
_SUMMARY_TITLE_LIMIT = 120

_SUMMARY_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "item": "项",
        "value": "内容",
        "title": "标题",
        "author": "作者",
        "published": "发布时间",
        "source": "来源",
        "images": "图片",
        "size": "大小",
        "commit": "提交",
        "preview": "文章预览",
        "none": "—",
        "image_remote": "{n} 张，**全部远程链接**（image_mode: remote）",
        "image_local": "{n} 张，**已本地化到 vault**（image_mode: local）",
        "size_fmt": "{lines} 行 / {kb} KB",
        "warn_push_failed": "> ⚠️ 已提交但推送失败，vault 与远端可能不同步",
        "warn_commit_failed": "> ⚠️ Git 提交失败，笔记已写入但未提交",
        "warn_stage_failed": "> ⚠️ Git 暂存失败，笔记已写入但未提交",
        "warn_unverified": "> ⚠️ 提交已创建但校验未通过，未推送",
        "warn_verification_failed": "> ⚠️ Git 校验未通过，未提交也未推送",
    },
    "en": {
        "item": "Item",
        "value": "Value",
        "title": "Title",
        "author": "Author",
        "published": "Published",
        "source": "Source",
        "images": "Images",
        "size": "Size",
        "commit": "Commit",
        "preview": "Article preview",
        "none": "—",
        "image_remote": "{n}, **all remote** (image_mode: remote)",
        "image_local": "{n}, **localized into the vault** (image_mode: local)",
        "size_fmt": "{lines} lines / {kb} KB",
        "warn_push_failed": "> ⚠️ committed but the push failed; the vault may be out of sync",
        "warn_commit_failed": "> ⚠️ the Git commit failed; the note is written but not committed",
        "warn_stage_failed": "> ⚠️ Git staging failed; the note is written but not committed",
        "warn_unverified": "> ⚠️ the commit exists but verification failed; not pushed",
        "warn_verification_failed": "> ⚠️ Git verification failed; nothing was committed or pushed",
    },
}


# Untrusted page text containing one of these renders as active markup: a link,
# an image, an HTML element, a GFM autolink (`www.`, `://`, `@user`), emphasis or
# strikethrough. A code span is the only construct GFM renders literally —
# backslash escaping leaves `[x](url)` clickable and HTML entities are decoded
# before inline parsing.
_SUMMARY_MARKUP_MARKERS = (
    "](", "![", "<", ">", "`",  # link, image, HTML, code
    "*", "_", "~",  # emphasis, emphasis, strikethrough
    "www.", "://", "@",  # GFM autolink triggers
)


def _summary_cell(value: object) -> str:
    """Render a value as literal text inside a Markdown table cell.

    Values here are page-derived and untrusted, so a title such as
    ``[Claim prize](https://evil.example)`` or ``![x](https://evil/t.gif)`` must
    not become a clickable link or a remote image in the receipt. Ordinary text
    keeps its characters (backslashes doubled, pipes and ampersands neutralised);
    a value still carrying inline Markdown markers is wrapped in a code span.
    """
    text = str(value).replace("\r", " ").replace("\n", " ")
    if any(marker in text for marker in _SUMMARY_MARKUP_MARKERS):
        # Inside a code span a backslash is literal, so only the table's pipe
        # separator needs escaping; the fence is one backtick longer than the
        # longest run in the value so the span cannot be closed early.
        longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
        return f"{'`' * (longest + 1)} {text.replace('|', chr(92) + '|')} {'`' * (longest + 1)}"
    return text.replace("&", "&amp;").replace("\\", "\\\\").replace("|", "\\|")


@dataclass(frozen=True)
class ClipResult:
    path: str
    commit_state: str
    push_state: str
    github_url: str | None = None
    action: str = "clip"
    # Every note the operation touched; ``path`` is the first entry.
    paths: tuple[str, ...] = ()
    # Which frontmatter field resolved a hash selector, when applicable.
    matched_by: str | None = None
    # Report metadata. All defaulted so the public structured API stays compatible.
    title: str = ""
    author: str = ""
    published: str = ""
    source_host: str = ""
    image_mode: str = ""
    image_count: int = 0
    size_bytes: int = 0
    line_count: int = 0
    # The commit message subject that actually landed, verbatim from the commit.
    commit_subject: str = ""
    commit_sha: str = ""

    def _git_detail(self) -> str:
        if self.commit_state == "disabled":
            return "Git synchronization disabled"
        if self.commit_state == "committed" and self.push_state == "pushed":
            return "committed and pushed"
        if self.commit_state == "unchanged":
            return (
                "content unchanged; no Git commit needed"
                if self.action == "clip"
                else "already in the requested state; no Git commit needed"
            )
        if self.commit_state == "committed":
            return "committed; push failed"
        if self.commit_state == "committed_unverified":
            return (
                "local commit created, but post-commit verification failed; not pushed"
            )
        if self.commit_state == "commit_failed":
            return "Git commit failed; not pushed"
        if self.commit_state == "stage_failed":
            return "Git staging failed; not committed or pushed"
        return "Git safety verification refused synchronization; not committed or pushed"

    def user_message(self) -> str:
        headline = {
            "favorite": "Marked clip as favorite",
            "unfavorite": "Removed favorite marker from clip",
        }.get(self.action, "Saved clip")
        paths: tuple[str, ...] = tuple(self.paths) if self.paths else (self.path,)
        if len(paths) > 1:
            lines = [f"{headline} ({len(paths)} notes):"]
            lines.extend(f"- {path}" for path in paths)
            lines.append(f"({self._git_detail()}).")
            message = "\n".join(lines)
        else:
            message = f"{headline}: {paths[0]} ({self._git_detail()})."
        if self.matched_by == "source_content_hash":
            message += " Matched by source_content_hash."
        if self.github_url:
            message += f" GitHub: {self.github_url}"
        return message

    def summary_markdown(self, lang: str = "zh") -> str:
        """Markdown report for a finished clip.

        The table leads with the article title, then author, published date,
        source, images, note size and commit. The agent prints this verbatim
        instead of recomputing figures, so the numbers come from the plugin
        rather than from the model. Favorite marker operations keep the short
        ``user_message()`` form: a table of author, images and note size says
        nothing useful about them.
        """
        if self.action in {"favorite", "unfavorite"}:
            return self.user_message()
        labels = _SUMMARY_LABELS.get(lang, _SUMMARY_LABELS["zh"])
        rows = (
            # (label, value, untrusted). Only page-derived values are escaped: the
            # image and size cells are plugin-generated and carry their own
            # Markdown emphasis, which escaping would turn into literal asterisks.
            (labels["title"], self._summary_title(labels), True),
            (labels["author"], self.author or labels["none"], True),
            (labels["published"], self.published or labels["none"], True),
            (labels["source"], self.source_host or labels["none"], True),
            (labels["images"], self._summary_images(labels), False),
            (labels["size"], self._summary_size(labels), False),
            (labels["commit"], self._summary_commit(labels), True),
        )
        lines = [
            f"| {labels['item']} | {labels['value']} |",
            "| --- | --- |",
            *(
                f"| {_summary_cell(name)} | "
                f"{_summary_cell(value) if untrusted else value} |"
                for name, value, untrusted in rows
            ),
        ]
        warning = self._summary_warning(labels)
        if warning:
            lines.extend(("", warning))
        if self.github_url:
            lines.extend(("", f"[{labels['preview']}]({self.github_url})"))
        return "\n".join(lines)

    def _summary_warning(self, labels: Mapping[str, str]) -> str:
        """One line, only when synchronization did not fully succeed.

        A successful push prints nothing extra, so the receipt stays a plain
        table; a failed push or commit must not look like a clean clip.
        """
        if self.commit_state == "committed" and self.push_state == "push_failed":
            return labels["warn_push_failed"]
        if self.commit_state == "committed_unverified":
            return labels["warn_unverified"]
        if self.commit_state in {
            "commit_failed",
            "stage_failed",
            "verification_failed",
        }:
            return labels[f"warn_{self.commit_state}"]
        return ""

    def _summary_title(self, labels: Mapping[str, str]) -> str:
        """Article title, capped so one long <title> cannot dominate the receipt."""
        title = self.title.strip()
        if not title:
            return labels["none"]
        if len(title) <= _SUMMARY_TITLE_LIMIT:
            return title
        return f"{title[:_SUMMARY_TITLE_LIMIT]}…"

    def _summary_images(self, labels: Mapping[str, str]) -> str:
        if self.image_count <= 0:
            return labels["none"]
        template = (
            labels["image_local"] if self.image_mode == "local" else labels["image_remote"]
        )
        return template.format(n=self.image_count)

    def _summary_size(self, labels: Mapping[str, str]) -> str:
        if self.line_count <= 0:
            return labels["none"]
        return labels["size_fmt"].format(
            lines=self.line_count, kb=f"{self.size_bytes / 1024:.1f}"
        )

    def _summary_commit(self, labels: Mapping[str, str]) -> str:
        if not self.commit_sha:
            return labels["none"]
        if self.commit_subject:
            return f"{self.commit_sha} {self.commit_subject}"
        return self.commit_sha


@dataclass(frozen=True)
class PendingClipResult:
    title: str
    image_count: int

    def user_message(self) -> str:
        noun = "image" if self.image_count == 1 else "images"
        return (
            f"Found {self.image_count} remote {noun} in '{self.title}'. "
            "Reply yes or no: yes downloads and localizes them, no keeps the remote image URLs."
        )


def _batch_label(selector: str) -> str:
    """Shorten a sha256 selector for batch summaries; URLs pass through."""
    if selector.startswith("sha256:") and len(selector) > 27:
        return f"{selector[:19]}…"
    return selector


@dataclass(frozen=True)
class BatchClipItem:
    url: str
    ok: bool
    path: str | None = None
    action: str = "clip"
    error: str | None = None


@dataclass(frozen=True)
class BatchClipResult:
    items: tuple[BatchClipItem, ...]
    commit_state: str
    push_state: str
    github_urls: tuple[str, ...] = ()

    def user_message(self) -> str:
        saved = [item for item in self.items if item.ok]
        failed = [item for item in self.items if not item.ok]
        lines = [f"Batch clip: {len(saved)} saved, {len(failed)} failed."]
        if self.commit_state == "disabled":
            lines.append("Git synchronization disabled for this batch.")
        elif self.commit_state == "committed" and self.push_state == "pushed":
            lines.append("Saved notes were committed and pushed together in one commit.")
        elif self.commit_state == "unchanged":
            lines.append("No content changes; no Git commit was needed.")
        elif self.commit_state == "committed":
            lines.append("Saved notes were committed together; push failed.")
        else:
            lines.append(
                f"Git state: {self.commit_state}/{self.push_state}; "
                "saved notes remain on disk."
            )
        lines.extend(f"- saved: {item.path}" for item in saved)
        lines.extend(
            f"- failed: {_batch_label(item.url)} ({item.error})" for item in failed
        )
        lines.extend(f"GitHub: {url}" for url in self.github_urls)
        return "\n".join(lines)


def _format_published(value: object) -> str:
    """``2026-11-14 03:07:09`` / ISO → ``2026-11-14 03:07``; other text passes through."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?", text)
    if match:
        date, clock = match.group(1), match.group(2)
        return f"{date} {clock}" if clock else date
    return text


def _article_report_fields(
    article: Mapping[str, object] | None,
) -> tuple[str, str, str, str]:
    """(title, author, published, host) for the clip summary."""
    if not article:
        return "", "", "", ""
    title = str(article.get("title") or "").strip()
    author = str(article.get("author") or "").strip()
    published = _format_published(article.get("published"))
    source = str(article.get("canonicalUrl") or article.get("url") or "").strip()
    host = urlsplit(source).netloc.lower() if source else ""
    return title, author, published, host


def _note_size(path: Path) -> tuple[int, int]:
    """(bytes, lines) of the written note; (0, 0) when it cannot be read."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0, 0
    if not data:
        return 0, 0
    return len(data), data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _ensure_no_secret_markers(note: str) -> None:
    if any(pattern.search(note) for pattern in _SECRET_PATTERNS):
        raise ClipError("The extracted page contains a credential-like marker; refusing to save it.")
