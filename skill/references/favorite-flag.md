# Favorite Flag Reference

## Purpose

The favorite flag lets the user mark a clipped note without re-clipping it. It lives in frontmatter as a boolean key managed by the plugin:

```yaml
favorite: true
```

If the key is absent, the note is not favorited. The plugin never writes `favorite: false`.

## Behavior

| Action | Result | Persistence requirement |
|--------|--------|------------------------|
| `/webclip <url> --favorite` | new or existing note gets `favorite: true` | `write_managed_note()` may return unchanged; follow up with `set_frontmatter_flag()` if the flag is still missing |
| `/webclip-favorite <url>` | existing note gets `favorite: true` | `set_frontmatter_flag()` + `GitSync.finalize()` |
| `/webclip-favorite <url> --unfavorite` | removes `favorite` from frontmatter | `set_frontmatter_flag()` + `GitSync.finalize()` |
| Re-clip without `--favorite` | does not remove an existing favorite flag | same write path |

## Implementation notes

- `_note_semantic_state()` intentionally ignores `favorite` when comparing note state, so adding or removing the flag does not require `--refresh`.
- `set_frontmatter_flag()` only mutates managed webclip notes; it refuses notes without `webclip_id`.
- The flag is stored as YAML `favorite: true`, not as a tag, to keep bookmark intent separate from topic tags.
- Repo docs: `~/.hermes/workspace/coder/20261023-222954-webclip-favorite-flag/02-技术设计.md` contains the full design.
