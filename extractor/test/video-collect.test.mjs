import assert from 'node:assert/strict';
import test from 'node:test';

import { parseHTML } from 'linkedom';

import { meetsQualityGate } from '../src/extractor.mjs';
import { collectVideos } from '../src/video-collect.mjs';

const PAGE_URL = 'https://example.com/news/a/ABC123.html';

function collect(html, pageUrl = PAGE_URL) {
  const { document } = parseHTML(html);
  return collectVideos(document, pageUrl);
}

test('clamps page-declared dimensions and trims titles to the Python limits', () => {
  const found = collect(`
    <html><head><title>${'t'.repeat(20000)}</title></head><body>
      <video src="/clip.mp4" width="100001" height="-5"></video>
    </body></html>`);

  assert.equal(found.length, 1);
  assert.equal(found[0].width, 100000);
  assert.equal(found[0].height, 0);
  assert.ok(Buffer.byteLength(found[0].title, 'utf8') <= 10000);
});

test('responsive image sources cannot displace the video candidate', () => {
  const sources = Array.from({ length: 20 }, (_, i) => `<source src="/img-${i}.png">`).join('');
  const found = collect(`
    <html><body>
      <picture>${sources}</picture>
      <video><source src="/clip.mp4"></video>
    </body></html>`);

  assert.deepEqual(found.map(item => item.src), ['https://example.com/clip.mp4']);
});

test('a source URL over the byte budget is skipped, not passed on', () => {
  // The Python validator rejects a `src` beyond MAX_SRC_BYTES, and a rejected
  // candidate used to fail the whole extraction; the collector must drop it.
  const huge = `https://example.com/${'a'.repeat(9000)}.mp4`;
  const found = collect(`
    <html><body>
      <video><source src="${huge}"></video>
      <video><source src="/ok.mp4"></video>
    </body></html>`);

  assert.deepEqual(found.map(item => item.src), ['https://example.com/ok.mp4']);
});

test('collects a plain video[src] with its caption, poster and dimensions', () => {
  const found = collect(`
    <html><head><title>Page title</title></head><body>
      <video src="/media/clip.mp4" title="Clip title" poster="/poster.jpg"
             width="1280" height="720"></video>
    </body></html>`);

  assert.equal(found.length, 1);
  assert.equal(found[0].src, 'https://example.com/media/clip.mp4');
  assert.equal(found[0].type, 'video/mp4');
  assert.equal(found[0].title, 'Clip title');
  assert.equal(found[0].poster, 'https://example.com/poster.jpg');
  assert.equal(found[0].width, 1280);
  assert.equal(found[0].height, 720);
  assert.equal(found[0].origin, 'video-src');
});

test('resolves protocol-relative data-m3u8 and ignores the literal "undefined" in data-mp4', () => {
  const found = collect(`
    <html><body>
      <video data-mp4="undefined" data-m3u8="//flv0.example.net/abc.m3u8" src=""></video>
    </body></html>`);

  assert.equal(found.length, 1);
  assert.equal(found[0].src, 'https://flv0.example.net/abc.m3u8');
  assert.equal(found[0].type, 'application/x-mpegURL');
  assert.equal(found[0].origin, 'video-data');
});

test('collects every player on the page, in document order', () => {
  const found = collect(`
    <html><body>
      <video src="https://cdn.example.com/one.mp4" title="First"></video>
      <video src="https://cdn.example.com/two.mp4" title="Second"></video>
    </body></html>`);

  assert.deepEqual(
    found.map(item => item.title),
    ['First', 'Second'],
  );
});

test('collects source[src] with its declared type', () => {
  const found = collect(`
    <html><body>
      <video title="Series"><source src="/a/clip.webm" type="video/webm"></video>
    </body></html>`);

  assert.equal(found.length, 1);
  assert.equal(found[0].src, 'https://example.com/a/clip.webm');
  assert.equal(found[0].type, 'video/webm');
  assert.equal(found[0].title, 'Series');
  assert.equal(found[0].origin, 'source');
});

test('collects og:video and JSON-LD VideoObject contentUrl', () => {
  const found = collect(`
    <html><head>
      <meta property="og:video" content="https://cdn.example.com/og.mp4">
      <meta property="og:image" content="https://cdn.example.com/og.jpg">
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"VideoObject","contentUrl":"https://cdn.example.com/ld.mp4"}
      </script>
    </head><body></body></html>`);

  assert.deepEqual(
    found.map(item => item.origin).sort(),
    ['json-ld', 'og-video'],
  );
  const og = found.find(item => item.origin === 'og-video');
  assert.equal(og.poster, 'https://cdn.example.com/og.jpg');
});

test('de-duplicates the same address across attributes and tags', () => {
  const found = collect(`
    <html><body>
      <video src="https://cdn.example.com/same.mp4" data-src="https://cdn.example.com/same.mp4"></video>
      <source src="https://cdn.example.com/same.mp4">
    </body></html>`);

  assert.equal(found.length, 1);
});

test('rejects non-http schemes, credentials and unparseable values', () => {
  const found = collect(`
    <html><body>
      <video src="javascript:alert(1)"></video>
      <video src="file:///etc/passwd"></video>
      <video src="https://user:pass@cdn.example.com/x.mp4"></video>
      <video src="   "></video>
      <video data-m3u8="null"></video>
    </body></html>`);

  assert.equal(found.length, 0);
});

test('falls back to the figure caption, then the page title', () => {
  const found = collect(`
    <html><head><title>Fallback page title</title></head><body>
      <figure data-alt="Figure caption"><video src="https://cdn.example.com/a.mp4"></video></figure>
      <video src="https://cdn.example.com/b.mp4"></video>
    </body></html>`);

  assert.equal(found[0].title, 'Figure caption');
  assert.equal(found[1].title, 'Fallback page title');
});

test('caps the number of candidates', () => {
  const players = Array.from(
    { length: 25 },
    (_, index) => `<video src="https://cdn.example.com/${index}.mp4"></video>`,
  ).join('');
  const found = collect(`<html><body>${players}</body></html>`);

  assert.equal(found.length, 20);
});

test('a video stub clears the quality gate only when explicitly allowed', () => {
  const stub = {
    title: 'A video page',
    markdown: '<video></video>',
    videos: [{ src: 'https://cdn.example.com/a.m3u8' }],
  };

  assert.equal(meetsQualityGate(stub), false);
  assert.equal(meetsQualityGate({ ...stub, videos: [] }, { allowVideoStub: true }), false);
  assert.equal(meetsQualityGate(stub, { allowVideoStub: true }), true);
});
