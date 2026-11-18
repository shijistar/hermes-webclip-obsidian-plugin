# Direct Download (mp4, webm, …)

A single GET, streamed to disk, with a hard byte cap.

## Limits are enforced while writing, not from headers

`Content-Length` is advisory: chunked responses omit it, and some servers send a
wrong one. The downloader therefore counts bytes as they arrive and aborts the
moment the cap is crossed. A partial file is always deleted before the error is
reported.

Do not "check the size first with HEAD": CDNs answer `405`, or `200` with no
`Content-Length`, and the check gives false confidence.

## Redirects

Up to five hops. **Every hop is resolved and validated again** — a public URL
that 302s to `http://10.0.0.5/` is refused, which is the whole point of not
letting a generic HTTP client follow the chain.

## Rejected addresses

| Address | Reason |
| --- | --- |
| `10/8`, `172.16/12`, `192.168/16` | private |
| `127/8`, `::1` | loopback |
| `169.254/16` | link-local (cloud metadata endpoints) |
| `224/4`, `240/4` | multicast / reserved |
| any non-default port | page-supplied `:8082` is either unreachable P2P or an attempt to reach something else |

URLs carrying `user:pass@` are refused before resolution.

## Failure meanings

| Message | Cause |
| --- | --- |
| `blocked by network policy` | private/reserved address or non-default port |
| `could not be resolved` | DNS failure |
| `server returned HTTP 403` | hotlink protection — the site needs a `Referer`, which its adapter must supply |
| `server returned an empty file` | the URL was a placeholder |
| `redirected too many times` | more than five hops |

Hotlink protection is handled per site in the adapter's `headers()`, not by
guessing request headers globally.
