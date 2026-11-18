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

## Verifying the merged file

Compare the container duration with the sum of `EXTINF` — as a **ratio**, not an
absolute. Segment boundaries land on keyframes, so each part runs a few tens of
milliseconds past its declared value, and the error accumulates with segment
count. Measured on 2026-11-18, all five through the full command:

| Page | Segments | Container | Playlist | Residue | Per segment |
| --- | --- | --- | --- | --- | --- |
| `VKAVGKVBP` | 5 | 44.20s | 43.96s | 0.24s | 48ms |
| `VX92E7HC1` | 5 | 40.24s | 40.00s | 0.24s | 48ms |
| `VRB0KKUPI` | 11 | 251.79s | 251.16s | 0.63s | 57ms |
| `VX90A5AE9` | 11 | 231.99s | 231.36s | 0.63s | 57ms |
| `VN8BG1HND` | 56 | 1591.56s | 1587.76s | **3.80s** | 68ms |

Accept while the residue stays around 100 ms per segment — roughly
`max(3s, 1% of duration)` for a quick check. An absolute threshold such as
"under 3 seconds" is wrong: it passes every short clip and fails a 26-minute one
that is perfectly intact.

And the residue is **not** missing content. A dropped segment makes the container
*shorter* than the playlist sum by a whole segment length (12–28s here), never
longer by a few seconds. When that distinction matters, read the packet timeline —
no ffprobe needed:

```
ffmpeg -v error -i out.mp4 -map 0:v -c copy -f framecrc - \
  | awk -F', *' '/^#tb/{split($0,c,"/"); tb=c[2]+0; next} \
      !/^#/{p=$3/tb; if(n>0&&p-q>m){m=p-q; at=p} q=p; n++} \
      END{printf "packets=%d max_gap=%.3fs at %.2fs\n", n, m, at}'
```

`max_gap` must stay near the frame interval; a missing segment shows up as a gap
the size of that segment. Cross-check the packet count against
`duration × fps`. On the 56-segment sample: 39692 packets, `max_gap` 0.360s,
`last_pts` 1591.48s — consistent with the container, so nothing was lost.

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
