# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer:

```bash
cd "$HERMES_HOME/plugins/webclip-obsidian"
./post-install.sh
```

> If you have a custom Hermes home directory, specify it with the `--hermes-home` flag.
> `./post-install.sh --hermes-home /path/to/custom-hermes`

What it does:

1. `npm install` in the bundled `extractor/` directory — installs the Node dependencies
2. Symlinks the `web-clip-to-obsidian` skill into the profile's skills dir
3. Bootstraps `config.toml` from `config.example.toml` if absent.

<!-- If the plugin is _not_ installed yet (or you want to refresh an existing
install), pass `--install-plugin`. On an existing install this performs a
forced reinstall (`hermes plugins install --force`) and **preserves your
`config.toml`** — it is backed up before the reinstall and restored
afterwards; first-time installs are unchanged. -->

Then review `config.toml`, restart your Hermes gateway service from a separate
shell, and clip with `/webclip <url>`. You can also run the clip with natural
language: `clip to obsidian <url>`
