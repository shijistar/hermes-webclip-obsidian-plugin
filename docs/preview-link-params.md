# Opening preview links in a browser

After a successful clip the plugin returns a GitHub blob URL as the article
preview link (`ClipResult.github_url`). Some messaging clients open such links
in an in-app browser instead of the system browser. The `preview_url_params`
option in `config.toml` appends query parameters to that URL, which a few
clients use to hand the link to the system browser.

**Most platforms do not support a URL query parameter for this.** The table
below distinguishes the platforms that do, the ones that need a client or OS
setting, and the ones that only expose an in-app JSAPI. Read the platform row
before assuming a parameter will have any effect.

## Configuration

```toml
[clip]
preview_url_params = "lk_jump_to_browser=true&lk_mobile_jump_to_browser=true"
```

- Empty (the default) leaves the preview URL unchanged, byte for byte.
- The value is a `k=v&k2=v2` string; one optional leading `?` is accepted.
- Fragments (`#`), whitespace, control characters, values longer than 1024 bytes, and
  anything that is not a `k=v` pair are rejected when the
  config is loaded. The plugin raises `ClipError` rather than producing a
  malformed link.
- Parameters are appended to the preview URL only. They are never forwarded to
  the untrusted extractor process, and they have no meaning for GitHub itself.
- Equivalent environment variable: `WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS`.

## Per-platform reference

| Platform                                         | Mechanism                                                                | Parameter / setting              | URL query parameter works?      |
| ------------------------------------------------ | ------------------------------------------------------------------------ | -------------------------------- | ------------------------------- |
| Feishu / Lark (desktop)                          | Official URL parameter                                                   | `lk_jump_to_browser=true`        | Yes                             |
| Feishu / Lark (mobile)                           | Official URL parameter                                                   | `lk_mobile_jump_to_browser=true` | Yes                             |
| Feishu / Lark (client setting)                   | Settings -> Efficiency -> Link opening -> Prefer browser                 | —                                | No, it is a setting             |
| WeCom                                            | In-app JSAPI `ww.openDefaultBrowser({url})`                              | —                                | No                              |
| WeChat / WeCom desktop                           | "Use system default browser for third-party pages" / right-click menu    | —                                | No                              |
| DingTalk                                         | `openLink` JSAPI, AppLink container                                      | —                                | No                              |
| Telegram                                         | Settings -> In-App Browser / "Open external links in"                    | —                                | No                              |
| Slack / Discord                                  | System default browser                                                   | —                                | No                              |
| WhatsApp / Signal / other mobile in-app browsers | OS "Opening links" setting, "Open in Safari" / "Open in Chrome" menu     | —                                | No                              |
| GoodBarber-style WebView containers              | Container-specific `?gbOpenExternal=1`                                   | —                                | Yes, but only in that container |
| iOS Safari                                       | Scheme prefix `x-safari-https://`, `com-apple-mobilesafari-tab:https://` | —                                | No, it changes the scheme       |

## Feishu / Lark

The Feishu Open Platform documents two parameters in _Configure webpage to
open in browser_: `lk_jump_to_browser=true` on desktop URLs and
`lk_mobile_jump_to_browser=true` on mobile URLs. Clicking a page URL carrying
the parameter jumps to the browser instead of opening inside Feishu
([Feishu docs](https://open.feishu.cn/document/develop-web-apps/web-app-open-ability/configure-webpage-to-open-in-browser?lang=zh-CN),
[Lark English docs](https://open.larksuite.com/document/uYjL24iN/uMTMuMTMuMTM/web-app-open-ability/configure-webpage-to-open-in-browser),
[web app overview](https://open.feishu.cn/document/client-docs/h5/introduction?lang=zh-CN)).
No authentication is needed; the documented minimum versions are PC V7.7 and
Android/iOS V7.11.

The parameter takes precedence over the user's link-opening preference, over
the developer console's "Open in a new Lark tab" setting, and over both web-app
and general-webpage AppLinks. It does not apply when a page is reloaded in
place with `window.location.href`, and it is not supported in a standalone
Feishu window. The change is also recorded in the
[Feishu Open Platform changelog](https://open.feishu.cn/changelog?abilityType=Tool).

Combine both parameters in one value — desktop clients read the first and
mobile clients read the second:

```toml
preview_url_params = "lk_jump_to_browser=true&lk_mobile_jump_to_browser=true"
```

**Scope caveat.** The official documentation describes web apps, workbench,
main-navigation and search entries, and AppLinks. It does **not** state whether
a plain `https://` link inside a chat message is handled the same way. Verify
by clicking the preview link in your own client before relying on it. If it
has no effect, use the client setting instead: Settings -> Efficiency -> Link
opening -> Prefer browser
([Feishu help](https://www.feishu.cn/hc/zh-CN/articles/360038713913-%E8%AE%BE%E7%BD%AE%E4%BA%91%E6%96%87%E6%A1%A3%E7%9A%84%E9%BB%98%E8%AE%A4%E6%89%93%E5%BC%80%E6%96%B9%E5%BC%8F)).
The default browser Feishu uses can also be configured separately
([Feishu help](https://www.feishu.cn/hc/zh-CN/articles/360049067759-%E5%B0%86%E7%B3%BB%E7%BB%9F%E6%B5%8F%E8%A7%88%E5%99%A8%E8%AE%BE%E7%BD%AE%E4%B8%BA%E9%A3%9E%E4%B9%A6%E7%BD%91%E9%A1%B5%E7%89%88%E6%94%AF%E6%8C%81%E7%9A%84%E6%B5%8F%E8%A7%88%E5%99%A8)).

## Platforms without a URL parameter

WeCom exposes `ww.openDefaultBrowser({url})`
([WeCom developer docs](https://developer.work.weixin.qq.com/document/path/100518))
and DingTalk exposes `openLink`
([DingTalk docs](https://open.dingtalk.com/document/isvapp/jsapi-open-link),
[AppLink docs](https://open.dingtalk.com/document/development/open-normal-page)),
but both are JSAPIs callable only from inside an application page; they cannot
be appended to a link in a chat message. On desktop, WeChat and WeCom provide
a "use system default browser for third-party pages" setting and a built-in
browser menu, which are user-side settings rather than URL parameters
([community discussion](https://www.zhihu.com/question/512108306)).

Telegram's behaviour is controlled by client settings (In-App Browser and
"Open external links in"); community answers explicitly state that Telegram
cannot be told to use an external browser through the URL
([Stack Overflow](https://stackoverflow.com/questions/79997452/how-to-force-a-link-to-open-in-the-system-browser-from-telegrams-in-app-browser),
[Telegram bug tracker](https://bugs.telegram.org/c/42889),
[Telegram iOS Mini Apps issue](https://github.com/TelegramMessenger/Telegram-iOS/issues/1670)).
Slack and Discord desktop clients use the system default browser, which is
changed in the OS or client settings
([Slack discussion](https://stackoverflow.com/questions/60972374/slack-change-browser-to-open-links-from-desktop-app),
[Discord support](https://support.discord.com/hc/nl/community/posts/360030214512-Ability-to-change-browser-to-open-links?page=2)).
Mobile in-app browsers rely on the OS "Opening links" setting or the "Open in
Safari" / "Open in Chrome" menu
([U2L AI](https://u2l.ai/blog/open-link-in-default-browser)).

## Schemes and container-specific parameters

`?gbOpenExternal=1` is a GoodBarber convention for its generated WebView apps
([GoodBarber help](https://www.goodbarber.com/help/embed-external-web-pages-r33/open-links-in-an-external-browser-a145/)),
not a messaging-platform standard. iOS Safari can be targeted with
`x-safari-https://` or `com-apple-mobilesafari-tab:https://`
([Tietze](https://christiantietze.de/posts/2023/05/safari-for-mac-url-scheme/),
[iOSProgramming](https://www.reddit.com/r/iOSProgramming/comments/tpuowz/figured_out_safari_url_scheme/)),
but those replace the URL scheme instead of appending a query parameter, and
WeChat's in-app browser restricts arbitrary scheme launches
([CSDN](https://ask.csdn.net/questions/9340818)). None of these are usable
through `preview_url_params`.

## Sources

- [Feishu Open Platform: Configure webpage to open in browser](https://open.feishu.cn/document/develop-web-apps/web-app-open-ability/configure-webpage-to-open-in-browser?lang=zh-CN)
- [Lark Developer: Configure webpage to open in browser](https://open.larksuite.com/document/uYjL24iN/uMTMuMTMuMTM/web-app-open-ability/configure-webpage-to-open-in-browser)
- [Feishu Open Platform: Web app overview](https://open.feishu.cn/document/client-docs/h5/introduction?lang=zh-CN)
- [Feishu Help Center: Default link open behaviour](https://www.feishu.cn/hc/zh-CN/articles/360038713913-%E8%AE%BE%E7%BD%AE%E4%BA%91%E6%96%87%E6%A1%A3%E7%9A%84%E9%BB%98%E8%AE%A4%E6%89%93%E5%BC%80%E6%96%B9%E5%BC%8F)
- [Feishu Help Center: Set a supported system browser](https://www.feishu.cn/hc/zh-CN/articles/360049067759-%E5%B0%86%E7%B3%BB%E7%BB%9F%E6%B5%8F%E8%A7%88%E5%99%A8%E8%AE%BE%E7%BD%AE%E4%B8%BA%E9%A3%9E%E4%B9%A6%E7%BD%91%E9%A1%B5%E7%89%88%E6%94%AF%E6%8C%81%E7%9A%84%E6%B5%8F%E8%A7%88%E5%99%A8)
- [Feishu Open Platform changelog](https://open.feishu.cn/changelog?abilityType=Tool)
- [WeCom: openDefaultBrowser](https://developer.work.weixin.qq.com/document/path/100518)
- [Zhihu: WeCom in-app browser discussion](https://www.zhihu.com/question/512108306)
- [DingTalk: openLink](https://open.dingtalk.com/document/isvapp/jsapi-open-link)
- [DingTalk: Open a normal page](https://open.dingtalk.com/document/development/open-normal-page)
- [Stack Overflow: force system browser from Telegram in-app browser](https://stackoverflow.com/questions/79997452/how-to-force-a-link-to-open-in-the-system-browser-from-telegrams-in-app-browser)
- [Telegram bug tracker: in-app browser settings](https://bugs.telegram.org/c/42889)
- [Telegram iOS: openLink opens external browser](https://github.com/TelegramMessenger/Telegram-iOS/issues/1670)
- [Slack: change browser for links](https://stackoverflow.com/questions/60972374/slack-change-browser-to-open-links-from-desktop-app)
- [Discord: change browser for links](https://support.discord.com/hc/nl/community/posts/360030214512-Ability-to-change-browser-to-open-links?page=2)
- [U2L AI: why links open in an in-app browser](https://u2l.ai/blog/open-link-in-default-browser)
- [GoodBarber: open links in an external browser](https://www.goodbarber.com/help/embed-external-web-pages-r33/open-links-in-an-external-browser-a145/)
- [Christian Tietze: Safari URL scheme](https://christiantietze.de/posts/2023/05/safari-for-mac-url-scheme/)
- [r/iOSProgramming: Safari URL scheme](https://www.reddit.com/r/iOSProgramming/comments/tpuowz/figured_out_safari_url_scheme/)
- [CSDN: WeChat in-app browser scheme restrictions](https://ask.csdn.net/questions/9340818)
