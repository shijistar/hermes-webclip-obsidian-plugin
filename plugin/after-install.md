# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer:

```bash
cd "$HERMES_HOME/plugins/web-to-obsidian"

# CASE 1: install for the default profile
./install.sh

# CASE 2: install for a specific profile
./install.sh --profile <profile-name>

# CASE 3: install for a specific Hermes home
./install.sh --hermes-home <hermes-home-path>
```

What it does:

1. `npm install` — installs the `@tiny-codes/web-clip-extractor` npm package
   into this plugin directory (used at runtime as the Node extractor).
2. `npx playwright install chromium` — Chromium for dynamic-page fallback.
3. Symlinks the `web-clip-to-obsidian` skill into the profile's skills dir
   (needs `--repo /path/to/url-to-obsidian` if the source repo isn't next to
   this copy).
4. Bootstraps `config.toml` from `config.example.toml` if absent.

Then review `config.toml`, restart your Hermes gateway service from a separate
shell, and clip with `/webclip <url>`. You can also run the clip with natural language: `clip to obsidian <url>`
