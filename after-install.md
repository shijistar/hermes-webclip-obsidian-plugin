# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer:

```bash
cd "$HERMES_HOME/plugins/webclip-obsidian"

# post-install.sh auto-detects HERMES_HOME and the profile by walking up
# from its own location to the nearest .hermes directory — no flags needed.
./post-install.sh

# custom Hermes home
./post-install.sh --hermes-home /path/to/custom-hermes
```

What it does:

1. (Default) does **not** re-install the plugin — the plugin was already
   installed via `hermes plugins install` (this guide runs right after it).
   If the plugin is _not_ installed yet, pass `--install-plugin` to run
   `hermes plugins install "file://<repo>" --enable`.
2. `npm install` in the bundled `extractor/` directory — installs the Node
   dependencies; the package's `prepare` hook runs
   `npx playwright install chromium`, so the Playwright browser is installed
   automatically (no separate step needed).
3. Symlinks the `web-clip-to-obsidian` skill into the profile's skills dir
   (the skill ships inside the installed copy, so no source-repo argument is
   needed).
4. Bootstraps `config.toml` from `config.example.toml` if absent.

Then review `config.toml`, restart your Hermes gateway service from a separate
shell, and clip with `/webclip <url>`. You can also run the clip with natural
language: `clip to obsidian <url>`
