# HLS Download

The playback list is read before any media is fetched: a playlist costs
kilobytes, the video costs megabytes.

## Pre-flight, in this order

| Tag | Reading | Action |
| --- | --- | --- |
| `#EXT-X-KEY:METHOD=AES-128` or any non-`NONE` method | segments are encrypted | refuse and report; no key handling exists |
| `#EXT-X-STREAM-INF` | this is a master playlist | read the first variant and pre-flight it again (one level only) |
| no `#EXT-X-ENDLIST` | live stream | refuse; a download would be a partial recording |
| zero `#EXTINF` lines | no media | refuse; the URL is a player config, not a playlist |
| no `#EXTM3U` header | not a playlist | refuse; the page probably returned an HTML error document |

Duration is the sum of the `EXTINF` values and is what the receipt quotes when
the merged file's own duration cannot be read.

## Why ffmpeg never touches the network here

A playlist is page-controlled: its segment URLs can point at `127.0.0.1`,
`169.254.169.254`, or a hostname that resolves public first and private second.
ffmpeg's HTTP client has no SSRF guard and follows redirects by itself, so it
would happily fetch those.

Instead every segment is downloaded by the plugin's own pinned-connection
client, which resolves the host once, rejects private/link-local answers and
non-default ports, and revalidates each redirect. ffmpeg then receives a concat
list of **local files**:

```
ffmpeg -hide_banner -loglevel error -nostdin \
  -protocol_whitelist file \
  -f concat -safe 0 -i segments.txt -c copy out.mp4
```

`-protocol_whitelist file` means even a malicious entry in the concat list
cannot make ffmpeg open a URL. Stream copy only: no re-encode, so speed equals
bandwidth.

## Failure meanings

| Message | Cause |
| --- | --- |
| `encrypted (DRM or AES-128)` | key-protected segments; unsupported by design |
| `live stream` | no `ENDLIST`; the command refuses rather than truncating |
| `contains no segments` | the playlist parsed but carried no media |
| `larger than the configured size limit` | the byte cap tripped mid-write; the partial file is deleted |
| `Merging the downloaded stream failed` | ffmpeg could not concat the parts (usually mixed containers) |
| `playlist has too many segments` | over 5000 parts — almost always not a VOD film |

## Segment naming matters

The concat demuxer sniffs the container from each part's **extension**, so
segments are stored with the extension from their own URL (`.ts`, `.m4s`,
`.mp4`, …) and fall back to `.ts` when the URL has none.
