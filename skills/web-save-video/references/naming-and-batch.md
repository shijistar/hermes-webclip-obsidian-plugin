# Naming and Batch Rules

Filenames are user-visible, so the rules are fixed and boring.

| Situation | Result |
| --- | --- |
| `--name "My clip"` | `My clip.mp4` |
| no `--name`, title available | the video title, cleaned |
| no title at all | first 12 chars of the URL's sha256, plus the extension |
| one video from one URL | no numeric suffix |
| several videos, or several URLs in one command | `-1`, `-2`, … per page, in discovery order |
| a file with that name already exists | a further `-1` is appended (`Clip-1.mp4`), unless `--overwrite` |
| `--overwrite` | the existing file is replaced |

## Cleaning

- Characters `<>:"/\|?*` and control characters are removed.
- Whitespace collapses; a trailing dot or space is trimmed (Windows rejects them).
- The whole name is capped at **180 UTF-8 bytes**, suffix included — a Chinese
  title costs 3 bytes per character, so ~55 characters survive.
- DOS reserved stems (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) get a
  leading underscore.

## Extension

| Clue | Extension |
| --- | --- |
| `application/x-mpegURL` or an `.m3u8` URL | `.mp4` (HLS is remuxed) |
| `video/webm`, `video/quicktime`, … | `.webm`, `.mov`, … |
| unknown type, known URL suffix | that suffix |
| nothing usable | `.mp4` |

## Why the URL is rarely the name

CDN video URLs are opaque hashes (`e25593ed1075…m3u8`). Naming a file after one
produces something no human can recognise in a file manager, so the title — and
only as a last resort the hash — supplies the name.

## Batch ceiling

`[video].max_per_run` (default 10) caps how many files one command downloads.
Extra candidates are reported as `Skipped: the per-run limit … was reached`
rather than dropped silently.
