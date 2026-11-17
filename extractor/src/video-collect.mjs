/**
 * Video source discovery over an already-parsed DOM.
 *
 * The article extractor only keeps Defuddle's Markdown, where a player shows up
 * as an empty `<video>` tag: `absolutizeLinks()` rewrites anchors and `img`/
 * `source` sources but deliberately leaves `video[src]` and `data-*` alone. So
 * the media address has to be collected here, before Defuddle runs, and every
 * candidate has to be resolved against the page URL by us.
 *
 * What this module deliberately does NOT do is decide whether a host is public.
 * That check belongs to the download layer, which resolves DNS and pins the
 * connection; duplicating it here would reject legitimate CDN ports (Bilibili
 * serves streams from `:8082`) without adding protection, because the page
 * controls the string either way.
 */

const MAX_CANDIDATES = 20;
const MAX_JSON_LD_BYTES = 200_000;
const MAX_JSON_LD_SCRIPTS = 5;

/** Media attributes that carry a playable address, in preference order. */
const VIDEO_DATA_ATTRIBUTES = [
  'data-m3u8',
  'data-hls',
  'data-mp4',
  'data-video-url',
  'data-video',
  'data-src',
  'data-url',
];

const TYPE_BY_EXTENSION = {
  m3u8: 'application/x-mpegURL',
  mpd: 'application/dash+xml',
  mp4: 'video/mp4',
  webm: 'video/webm',
  mov: 'video/quicktime',
  mkv: 'video/x-matroska',
  flv: 'video/x-flv',
  ts: 'video/mp2t',
};

const PLACEHOLDER_VALUES = new Set(['', 'undefined', 'null', 'none', 'false']);

/** Resolve one raw attribute value against the page URL, or return null. */
function resolveCandidate(value, sourceUrl) {
  if (typeof value !== 'string') return null;
  const raw = value.trim();
  if (PLACEHOLDER_VALUES.has(raw.toLowerCase())) return null;
  let resolved;
  try {
    // `new URL(value, base)` is what makes protocol-relative `//host/x.m3u8`
    // work; a plain regex over `https?://` misses those pages entirely.
    resolved = new URL(raw, sourceUrl);
  } catch {
    return null;
  }
  if (resolved.protocol !== 'http:' && resolved.protocol !== 'https:') return null;
  if (resolved.username || resolved.password) return null;
  resolved.hash = '';
  return resolved;
}

function typeFromUrl(url, declared) {
  if (typeof declared === 'string' && declared.trim()) return declared.trim().toLowerCase();
  const extension = url.pathname.split('.').pop()?.toLowerCase() ?? '';
  return TYPE_BY_EXTENSION[extension] ?? '';
}

function numericAttribute(element, name) {
  const raw = element.getAttribute?.(name);
  if (!raw) return 0;
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

/** Title preference: the player's own title, its figure caption, then the page. */
function titleForPlayer(player, document) {
  const own = player.getAttribute?.('title');
  if (typeof own === 'string' && own.trim()) return own.trim();
  const figure = typeof player.closest === 'function' ? player.closest('figure') : null;
  const caption = figure?.getAttribute?.('data-alt');
  if (typeof caption === 'string' && caption.trim()) return caption.trim();
  const pageTitle = document.querySelector('title')?.textContent;
  return typeof pageTitle === 'string' ? pageTitle.trim() : '';
}

function collectJsonLdVideos(document) {
  const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')].slice(
    0,
    MAX_JSON_LD_SCRIPTS,
  );
  const found = [];
  const walk = (node, depth) => {
    if (depth > 8 || node === null || typeof node !== 'object') return;
    if (Array.isArray(node)) {
      for (const item of node) walk(item, depth + 1);
      return;
    }
    const types = Array.isArray(node['@type']) ? node['@type'] : [node['@type']];
    const isVideo = types.some(
      type => typeof type === 'string' && type.toLowerCase().includes('videoobject'),
    );
    if (isVideo && typeof node.contentUrl === 'string') found.push(node.contentUrl);
    for (const value of Object.values(node)) {
      if (value !== null && typeof value === 'object') walk(value, depth + 1);
    }
  };
  for (const script of scripts) {
    const text = (script.textContent ?? '').trim();
    if (!text || text.length > MAX_JSON_LD_BYTES) continue;
    try {
      walk(JSON.parse(text), 0);
    } catch {
      // Page-controlled JSON-LD is frequently malformed; a broken block must not
      // cost us the players we already found in the DOM.
    }
  }
  return found;
}

/**
 * Collect every playable candidate on the page.
 * @returns {Array<{src: string, type: string, title: string, poster: string, width: number, height: number, origin: string}>}
 */
export function collectVideos(document, sourceUrl) {
  const base = typeof sourceUrl === 'string' ? sourceUrl : sourceUrl?.href;
  if (!base) return [];

  const pageTitle = document.querySelector('title')?.textContent?.trim() ?? '';
  const candidates = [];
  const seen = new Set();

  const push = (rawValue, { origin, title, poster, width, height, declaredType }) => {
    if (candidates.length >= MAX_CANDIDATES) return;
    const resolved = resolveCandidate(rawValue, base);
    if (!resolved) return;
    const href = resolved.href;
    if (seen.has(href)) return;
    seen.add(href);
    const posterUrl = poster ? resolveCandidate(poster, base) : null;
    candidates.push({
      src: href,
      type: typeFromUrl(resolved, declaredType),
      title: title || pageTitle,
      poster: posterUrl ? posterUrl.href : '',
      width: width || 0,
      height: height || 0,
      origin,
    });
  };

  for (const player of document.querySelectorAll('video')) {
    const title = titleForPlayer(player, document);
    const poster = player.getAttribute('poster') ?? '';
    const width = numericAttribute(player, 'width');
    const height = numericAttribute(player, 'height');
    const declaredType = player.getAttribute('type') ?? '';
    push(player.getAttribute('src'), {
      origin: 'video-src',
      title,
      poster,
      width,
      height,
      declaredType,
    });
    // `data-mp4` can hold an m3u8 URL and article pages sometimes write the
    // literal string "undefined" there, so each attribute is a claim, not a
    // fact: resolveCandidate rejects the placeholders and the extension decides
    // the container.
    for (const attribute of VIDEO_DATA_ATTRIBUTES) {
      push(player.getAttribute(attribute), {
        origin: 'video-data',
        title,
        poster,
        width,
        height,
        declaredType: '',
      });
    }
  }

  for (const source of document.querySelectorAll('source[src]')) {
    const player = typeof source.closest === 'function' ? source.closest('video') : null;
    push(source.getAttribute('src'), {
      origin: 'source',
      title: player ? titleForPlayer(player, document) : '',
      poster: '',
      width: 0,
      height: 0,
      declaredType: source.getAttribute('type') ?? '',
    });
  }

  const metaSelectors = [
    'meta[property="og:video:secure_url"]',
    'meta[property="og:video:url"]',
    'meta[property="og:video"]',
    'meta[name="twitter:player:stream"]',
  ];
  for (const selector of metaSelectors) {
    for (const meta of document.querySelectorAll(selector)) {
      push(meta.getAttribute('content'), {
        origin: 'og-video',
        title: '',
        poster: document.querySelector('meta[property="og:image"]')?.getAttribute('content') ?? '',
        width: numericAttribute(meta, 'width'),
        height: numericAttribute(meta, 'height'),
        declaredType: '',
      });
    }
  }

  for (const contentUrl of collectJsonLdVideos(document)) {
    push(contentUrl, {
      origin: 'json-ld',
      title: '',
      poster: '',
      width: 0,
      height: 0,
      declaredType: '',
    });
  }

  return candidates;
}
