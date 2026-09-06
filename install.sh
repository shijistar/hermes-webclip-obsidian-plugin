#!/usr/bin/env bash
#
# install.sh — one-shot installer for the web-to-obsidian plugin stack.
#
# Lives at the repo root, which IS the plugin package (plugin.yaml sits at the
# root). `hermes plugins install` clones the whole repository, so installed
# copies retain `skill/`, `extractor/`, `config.example.toml` and this script
# — every step below resolves paths relative to the script's own directory and
# no extra source-repo argument is needed.
#
# Steps performed:
#   0. Resolve HERMES_HOME / profile (--hermes-home, --profile)
#   1. `hermes plugins install <this-repo> --enable` (skipped with --skip-plugin-install)
#   2. `npm install` inside the bundled `extractor/` package — the package's
#      `prepare` hook runs `npx playwright install chromium` automatically.
#   3. Symlink `skill/` into the target profile's skills dir (auto-discovery)
#   4. Copy `config.example.toml` → `config.toml` if absent
#   5. Print restart instructions
#
# Usage:
#   ./install.sh [--profile NAME] [--hermes-home DIR] [--skip-plugin-install]
#
# Defaults:
#   HERMES_HOME = $HERMES_HOME if set (not already a profile), else ~/.hermes
#   profile     = default (root ~/.hermes)
#   plugin src  = this repo root (the script's own directory)
#
set -euo pipefail

# ---------------------------------------------------------------- defaults
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HERMES_HOME_ARG=""
PROFILE_ARG=""
SKIP_PLUGIN_INSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home)
      HERMES_HOME_ARG="$2"; shift 2 ;;
    --profile)
      PROFILE_ARG="$2"; shift 2 ;;
    --skip-plugin-install)
      SKIP_PLUGIN_INSTALL=1; shift ;;
    -h|--help)
      sed -n '2,21p' "$0"; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Resolve HERMES_HOME (profile base dir).
if [[ -n "$HERMES_HOME_ARG" ]]; then
  HERMES_HOME="$HERMES_HOME_ARG"
elif [[ -z "${HERMES_HOME:-}" || "$HERMES_HOME" == *"/profiles/"* ]]; then
  # When HERMES_HOME is unset or already points at a profile (gateway injects
  # the active profile), fall back to the user default so `--profile` keeps
  # working instead of nesting under the running profile.
  HERMES_HOME="$HOME/.hermes"
fi

# A named profile lives under <HERMES_HOME>/profiles/<name>.
if [[ -n "$PROFILE_ARG" ]]; then
  PROFILE_DIR="$HERMES_HOME/profiles/$PROFILE_ARG"
  PLUGIN_DIR="$PROFILE_DIR/plugins/web-to-obsidian"
  SKILLS_DIR="$PROFILE_DIR/skills/productivity"
else
  PROFILE_DIR="$HERMES_HOME"
  PLUGIN_DIR="$HERMES_HOME/plugins/web-to-obsidian"
  SKILLS_DIR="$HERMES_HOME/skills/productivity"
fi

# The plugin package this script ships with is SCRIPT_DIR itself (repo root).
PLUGIN_SRC="$SCRIPT_DIR"

# The skill ships inside the plugin package (repo root / installed copy).
SKILL_SRC="$SCRIPT_DIR/skill"

info()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

info "HERMES_HOME = $HERMES_HOME"
info "Profile dir = $PROFILE_DIR"
info "Plugin src  = $PLUGIN_SRC"

# ------------------------------------------------------- 1. install plugin
if [[ "$SKIP_PLUGIN_INSTALL" -eq 1 ]]; then
  info "Skipping \`hermes plugins install\` (--skip-plugin-install)"
else
  if [[ -d "$PLUGIN_DIR" ]]; then
    ok "Plugin already installed at $PLUGIN_DIR (reinstall with \`hermes plugins install --force\`)"
  else
    info "Installing plugin from $PLUGIN_SRC ..."
    HERMES_HOME="$HERMES_HOME" \
      hermes plugins install "file://$PLUGIN_SRC" --enable
  fi
fi

test -d "$PLUGIN_DIR" || die "Plugin dir not found at $PLUGIN_DIR (run hermes plugins install first)"

# We operate on the INSTALLED plugin dir; if this script is already running
# from the installed dir, PLUGIN_DIR == SCRIPT_DIR and nothing extra is needed.
INSTALLED_PLUGIN_DIR="$PLUGIN_DIR"
if [[ "$(cd "$SCRIPT_DIR" && pwd)" != "$(cd "$INSTALLED_PLUGIN_DIR" && pwd)" ]]; then
  info "Script runs from $SCRIPT_DIR; installing dependencies into $INSTALLED_PLUGIN_DIR"
fi

# ----------------------------------------- 2. extractor npm + playwright
# The extractor is a bundled package at <plugin>/extractor. Running `npm install`
# inside it triggers the package's `prepare` hook, which runs
# `npx playwright install chromium` — no separate Playwright step needed.
if [[ -f "$INSTALLED_PLUGIN_DIR/extractor/package.json" ]]; then
  info "Installing extractor dependencies in $INSTALLED_PLUGIN_DIR/extractor ..."
  (cd "$INSTALLED_PLUGIN_DIR/extractor" && npm install)
  ok "Extractor installed (prepare hook ran npx playwright install chromium)"
else
  warn "No package.json in $INSTALLED_PLUGIN_DIR/extractor — extractor npm install skipped"
fi

# ------------------------------------------------------- 3. skill symlink
if [[ ! -d "$SKILL_SRC" ]]; then
  warn "Skill dir not found at $SKILL_SRC; skipping skill symlink."
else
  mkdir -p "$SKILLS_DIR"
  if [[ -e "$SKILLS_DIR/web-clip-to-obsidian" || -L "$SKILLS_DIR/web-clip-to-obsidian" ]]; then
    ok "Skill already linked at $SKILLS_DIR/web-clip-to-obsidian"
  else
    info "Symlinking skill $SKILL_SRC → $SKILLS_DIR/web-clip-to-obsidian"
    ln -s "$SKILL_SRC" "$SKILLS_DIR/web-clip-to-obsidian"
  fi
fi

# ------------------------------------------------ 4. config.toml bootstrap
if [[ ! -f "$INSTALLED_PLUGIN_DIR/config.toml" ]]; then
  if [[ -f "$SCRIPT_DIR/config.example.toml" ]]; then
    info "Bootstrapping config.toml from config.example.toml"
    cp "$SCRIPT_DIR/config.example.toml" "$INSTALLED_PLUGIN_DIR/config.toml"
  fi
fi
if [[ -f "$INSTALLED_PLUGIN_DIR/config.toml" ]]; then
  ok "config.toml at $INSTALLED_PLUGIN_DIR/config.toml — review vault/destination/sync_branch"
else
  warn "No config.toml present; create it manually"
fi

# ------------------------------------------------------------ 5. summary
cat <<EOF

\033[1;32mInstall summary\033[0m
  Plugin:     $INSTALLED_PLUGIN_DIR
  Extractor:  $INSTALLED_PLUGIN_DIR/extractor
  Skill:      $SKILLS_DIR/web-clip-to-obsidian
  Config:     $INSTALLED_PLUGIN_DIR/config.toml

Next steps:
  1. Review config.toml (vault, destination, sync_branch).
  2. Restart your Hermes gateway service from a separate shell so the
     installed plugin is picked up by the running gateway process.
  3. Clip:  /webclip https://example.com/article
EOF