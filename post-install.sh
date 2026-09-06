#!/usr/bin/env bash
#
# post-install.sh — one-shot post-install setup for the webclip-obsidian
# plugin stack.
#
# This script lives inside the installed plugin directory. `hermes plugins
# install` clones the whole repository into:
#   <HERMES_HOME>/plugins/webclip-obsidian/                    (default profile)
#   <HERMES_HOME>/profiles/<name>/plugins/webclip-obsidian/    (named profile)
# so HERMES_HOME is found by walking up from this script's own path until a
# `.hermes` directory is hit (or by the explicit `--hermes-home DIR` flag),
# and the profile is derived from the `profiles/<name>/` path segment when
# present, falling back to HERMES_HOME itself (default profile).
#
# Steps performed:
#   0. Resolve HERMES_HOME (--hermes-home or .hermes walk-up) and derive
#      PROFILE_DIR, PLUGIN_DIR, SKILLS_DIR.
#   1. Optionally `hermes plugins install <this-repo> --enable` — only when
#      `--install-plugin` is passed. By default the plugin is assumed to have
#      been installed already (`hermes plugins install` is the bootstrap), so
#      this step is skipped.
#   2. `npm install` in the plugin dir (pulls the published
#      @tiny-codes/web-clip-extractor dependency into node_modules), then
#      `npx playwright install chromium` explicitly — an npm dependency's
#      `prepare` hook is not run under npm's default allow-scripts policy.
#   3. Symlink `skill/` into the target profile's skills dir (auto-discovery)
#   4. Copy `config.example.toml` → `config.toml` if absent
#   5. Print restart instructions
#
# Usage:
#   ./post-install.sh [--hermes-home DIR] [--install-plugin]
#
# Defaults:
#   HERMES_HOME  = nearest `.hermes` directory above this script, or the
#                  value of --hermes-home when given
#   profile      = the profile containing this script (from the
#                  `profiles/<name>/` path segment), or the default profile
#                  (HERMES_HOME itself) when the script is not under a
#                  profile's plugins dir
#   plugin src   = this repo root (the script's own directory)
#   install      = do NOT run `hermes plugins install` (pass --install-plugin
#                  to run it)
#
set -euo pipefail

# ---------------------------------------------------------------- defaults
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HERMES_HOME_ARG=""
INSTALL_PLUGIN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home)
      HERMES_HOME_ARG="$2"; shift 2 ;;
    --install-plugin)
      INSTALL_PLUGIN=1; shift ;;
    -h|--help)
      sed -n '2,32p' "$0"; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# -------------------------------------------------- derive Hermes home paths
# If --hermes-home is given it is used verbatim as HERMES_HOME (custom home).
# Otherwise walk up from SCRIPT_DIR until a `.hermes` directory is found. The
# installed layouts are:
#   <HERMES_HOME>/plugins/webclip-obsidian/                 → default profile
#   <HERMES_HOME>/profiles/<name>/plugins/webclip-obsidian/ → named profile
_find_hermes_home() {
  local dir="$1"
  while [[ -n "$dir" && "$dir" != "/" ]]; do
    if [[ -d "$dir/.hermes" ]]; then
      printf '%s\n' "$dir/.hermes"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

if [[ -n "$HERMES_HOME_ARG" ]]; then
  HERMES_HOME="$HERMES_HOME_ARG"
elif ! HERMES_HOME="$(_find_hermes_home "$SCRIPT_DIR")"; then
  echo "[error] Could not locate a .hermes directory above $SCRIPT_DIR \
(use --hermes-home DIR to point at a custom Hermes home)" >&2
  exit 1
fi

# PROFILE_DIR rules:
#   1. if the script lives under <HERMES_HOME>/profiles/<name>/ and that
#      directory exists → PROFILE_DIR = <HERMES_HOME>/profiles/<name>;
#   2. else if <HERMES_HOME>/profiles/ contains exactly one profile → use it;
#   3. else PROFILE_DIR = HERMES_HOME (default profile).
PROFILE_DIR="$HERMES_HOME"
_derived_profile=""
if [[ "$SCRIPT_DIR" == *"/profiles/"* ]]; then
  _profiles_idx="${SCRIPT_DIR%%/plugins/*}"       # strip trailing /plugins/*
  if [[ "$_profiles_idx" == *"/profiles/"* ]]; then
    _derived_profile="${_profiles_idx#*"/profiles/"}"
    _derived_profile="${_derived_profile%%/*}"
  fi
fi
if [[ -n "$_derived_profile" && -d "$HERMES_HOME/profiles/$_derived_profile" ]]; then
  PROFILE_DIR="$HERMES_HOME/profiles/$_derived_profile"
elif [[ -d "$HERMES_HOME/profiles" ]]; then
  _profiles_candidates=("$HERMES_HOME"/profiles/*/)
  if [[ ${#_profiles_candidates[@]} -eq 1 && -d "${_profiles_candidates[0]}" ]]; then
    PROFILE_DIR="$(cd "${_profiles_candidates[0]}" && pwd)"
  fi
fi

PLUGIN_DIR="$PROFILE_DIR/plugins/webclip-obsidian"
SKILLS_DIR="$PROFILE_DIR/skills/productivity"

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
if [[ "$INSTALL_PLUGIN" -eq 1 ]]; then
  if [[ -d "$PLUGIN_DIR" ]]; then
    ok "Plugin already installed at $PLUGIN_DIR (reinstall with \`hermes plugins install --force\`)"
  else
    info "Installing plugin from $PLUGIN_SRC ..."
    HERMES_HOME="$HERMES_HOME" \
      hermes plugins install "file://$PLUGIN_SRC" --enable
  fi
else
  info "Skipping \`hermes plugins install\` (install assumed already done; pass --install-plugin to run it)"
fi

test -d "$PLUGIN_DIR" || die "Plugin dir not found at $PLUGIN_DIR (run hermes plugins install first — or pass --install-plugin)"

# We operate on the INSTALLED plugin dir; if this script is already running
# from the installed dir, PLUGIN_DIR == SCRIPT_DIR and nothing extra is needed.
INSTALLED_PLUGIN_DIR="$PLUGIN_DIR"
if [[ "$(cd "$SCRIPT_DIR" && pwd)" != "$(cd "$INSTALLED_PLUGIN_DIR" && pwd)" ]]; then
  info "Script runs from $SCRIPT_DIR; installing dependencies into $INSTALLED_PLUGIN_DIR"
fi

# ----------------------------------------- 2. extractor npm + playwright
# The plugin declares @tiny-codes/web-clip-extractor as an npm dependency
# (installed into plugin/node_modules). The extractor also ships inside the
# plugin as <plugin>/extractor for source checkouts. Because npm dependencies'
# `prepare` hooks are skipped under npm's default allow-scripts policy, we run
# `npx playwright install chromium` explicitly here.
if [[ -f "$INSTALLED_PLUGIN_DIR/package.json" ]]; then
  info "Installing extractor npm package in $INSTALLED_PLUGIN_DIR ..."
  (cd "$INSTALLED_PLUGIN_DIR" && npm install)
  info "Installing Playwright Chromium ..."
  (cd "$INSTALLED_PLUGIN_DIR" && npx playwright install chromium)
  ok "Extractor installed"
else
  warn "No package.json in $INSTALLED_PLUGIN_DIR — extractor npm install skipped"
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
  Extractor:  $INSTALLED_PLUGIN_DIR/node_modules/@tiny-codes/web-clip-extractor
  Skill:      $SKILLS_DIR/web-clip-to-obsidian
  Config:     $INSTALLED_PLUGIN_DIR/config.toml

Next steps:
  1. Review config.toml (vault, destination, sync_branch).
  2. Restart your Hermes gateway service from a separate shell so the
     installed plugin is picked up by the running gateway process.
  3. Clip:  /webclip https://example.com/article
EOF