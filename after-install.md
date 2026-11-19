# Finish the install

`post-install.sh` ships inside the plugin and finishes setup in one step. Run it
in the profile you installed the plugin into — the default profile or a named
one.

## Ask Hermes to run it

Tell Hermes, in your profile chat:

> Run the post-install.sh inside the webclip-obsidian plugin.

## Or run it manully in a shell

Default profile:

```bash
~/.hermes/plugins/webclip-obsidian/post-install.sh
```

Named profile:

```bash
~/.hermes/profiles/<profile>/plugins/webclip-obsidian/post-install.sh
```

Custom hermes dir: a Hermes home outside `~/.hermes` (say `/data/hermes`) cannot be found by
walking up from the plugin, so pass it: `./post-install.sh --hermes-home /data/hermes`.

What it does:

1. `npm install` in the bundled `extractor/` — Node dependencies, plus
   Playwright Chromium through the package's `prepare` hook.
2. Downloads the standalone yt-dlp binary (checksum-verified) into the Hermes
   home's `tools/yt-dlp/` (`~/.hermes/tools` by default), so YouTube works
   without Homebrew or deno; skip it with `--no-youtube`, re-fetch with
   `--force-ytdlp`.
3. Creates `config.toml` from `config.example.toml` when it is absent.

Re-running is safe: `npm install` is incremental, an existing yt-dlp is kept,
and `config.toml` is never overwritten.

Then review `config.toml` (`vault`, `destination`, `sync_branch`, and
`preview_url_params` — see `docs/preview-link-params.md`), restart the gateway
so it loads the plugin (`hermes gateway restart`), and clip with
`/webclip <url>` or in plain language (`clip to obsidian <url>`).
