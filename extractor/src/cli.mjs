#!/usr/bin/env node

import { extractUrl } from './extractor.mjs';

const PUBLIC_ERRORS = {
  INVALID_URL: 'The URL is malformed.',
  UNSUPPORTED_SCHEME: 'Only HTTP and HTTPS URLs are allowed.',
  URL_CREDENTIALS: 'URLs containing credentials are not allowed.',
  NON_DEFAULT_PORT: 'Non-default ports are not allowed.',
  DNS_FAILED: 'The hostname could not be resolved.',
  BLOCKED_ADDRESS: 'The destination is blocked by network policy.',
  TOO_MANY_REDIRECTS: 'The page redirected too many times.',
  INVALID_REDIRECT: 'The page returned an invalid redirect.',
  TIMEOUT: 'The extraction timed out.',
  NETWORK_ERROR: 'The page request failed.',
  HTTP_STATUS: 'The server returned an unsuccessful status.',
  UNSUPPORTED_CONTENT_TYPE: 'The response is not HTML.',
  UNSUPPORTED_ENCODING: 'The response uses an unsupported encoding.',
  BODY_TOO_LARGE: 'The response body is too large.',
  INVALID_RESPONSE: 'The server returned an invalid response.',
  EXTRACTION_FAILED: 'Article extraction failed.',
  QUALITY_GATE: 'The page did not contain a substantial article.',
  BROWSER_FAILED: 'Browser extraction failed.',
  CHALLENGE_PAGE: 'The site served a browser challenge instead of the page.',
  FAKE_SUCCESS: 'The page did not contain the article its title promised.',
  USAGE: 'Usage: node src/cli.mjs <url> [--no-browser] [--with-videos]',
};

function output(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

async function main(argv) {
  const args = [...argv];
  const noBrowserIndex = args.indexOf('--no-browser');
  const noBrowser = noBrowserIndex !== -1;
  if (noBrowser) args.splice(noBrowserIndex, 1);
  const withVideosIndex = args.indexOf('--with-videos');
  const withVideos = withVideosIndex !== -1;
  if (withVideos) args.splice(withVideosIndex, 1);
  if (args.length !== 1 || args[0].startsWith('--')) {
    output({ ok: false, error: PUBLIC_ERRORS.USAGE, code: 'USAGE' });
    process.exitCode = 1;
    return;
  }

  try {
    const result = await extractUrl(args[0], { allowBrowser: !noBrowser, withVideos });
    output({ ok: true, ...result });
  } catch (cause) {
    const code = typeof cause?.code === 'string' && Object.hasOwn(PUBLIC_ERRORS, cause.code)
      ? cause.code
      : 'EXTRACTION_FAILED';
    const payload = { ok: false, error: PUBLIC_ERRORS[code], code };
    // Machine-readable context: without the status a caller cannot tell a bot
    // wall (403) from an auth failure (401) or a rate limit (429).
    const details = cause?.details;
    if (details && typeof details === 'object') {
      if (Number.isInteger(details.status)) payload.status = details.status;
      for (const key of ['retryAfter', 'cfMitigated', 'server']) {
        if (typeof details[key] === 'string' && details[key]) payload[key] = details[key].slice(0, 64);
      }
    }
    output(payload);
    process.exitCode = 1;
  }
}

await main(process.argv.slice(2));
