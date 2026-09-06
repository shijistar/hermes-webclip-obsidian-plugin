# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer:

```bash
cd "$HERMES_HOME/plugins/webclip-obsidian"

# CASE 1: install for the default profile
./install.sh

# CASE 2: install for a specific profile
./install.sh --profile <profile-name>

# CASE 3: install for a specific Hermes home
./install.sh --hermes-home <hermes-home-path>
```

What it does:

1. `hermes plugins install` — clones this repository (the plugin package;
   `plugin.yaml` sits at the repo root) and enables the plugin.
2. `npm install` inside the bundled `extractor/` package — the package's
   `prepare` hook runs `npx playwright install chromium` automatically, so
   Chromium for the dynamic-page fallback is installed with it.
3. Symlinks the `web-clip-to-obsidian` skill into the profile's skills dir
   (the skill ships inside the installed copy, so no source-repo argument is
   needed).
4. Bootstraps `config.toml` from `config.example.toml` if absent.

Then review `config.toml`, restart your Hermes gateway service from a separate
shell, and clip with `/webclip <url>`. You can also run the clip with natural
language: `clip to obsidian <url>`