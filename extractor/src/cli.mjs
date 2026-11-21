#!/usr/bin/env node

import { extractUrl } from './extractor.mjs';
import { PUBLIC_ERRORS, errorPayload } from './error-payload.mjs';

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
    output(errorPayload(cause));
    process.exitCode = 1;
  }
}

await main(process.argv.slice(2));
