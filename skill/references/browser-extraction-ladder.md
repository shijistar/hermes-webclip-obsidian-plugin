# Browser extraction: which path to take

Climb in order. Most pages never reach step 3.

| Step | Method | When it applies | Platform |
| --- | --- | --- | --- |
| 1 | Bundled extractor (Playwright Chromium, default) | Any JS-rendered article | all |
| 2 | `web_extract` | The extractor returned "no substantial article" | all |
| 3 | `curl` + regex | Static HTML, or a known site fallback (WeChat, Netease video) | all |
| 4 | Real browser + CDP | The page needs a **logged-in** session | see below |

## Platform notes for step 4

| Platform | Session source | Document |
| --- | --- | --- |
| Linux / macOS | Local Chrome, throwaway `--user-data-dir` | `platforms/linux-macos.md` |
| WSL | Chrome on the Windows host, driven through `powershell.exe` | `platforms/wsl.md` |

WSL cannot reuse a local Chrome session — there is none — which is why it borrows the
Windows one. That is a session problem, not a rendering problem: Playwright already
renders in WSL.

## Do not

- Do not start with CDP. It needs a visible browser, a free port, and a manual shutdown.
- Do not write video/image bytes through `document.body.innerText`; it is text only.
- Do not reuse the user's default Chrome profile for scraping.
