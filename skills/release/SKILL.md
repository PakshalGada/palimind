---
name: palimind-release
description: >
  How Palimind versions, tags, and ships installers for Windows/macOS/Linux.
  Use when cutting a release, bumping versions, or debugging the release
  pipeline. Triggers: release, tag, version, installer, signing, changelog.
---

# Releasing Palimind

## Versioning

- Single version source per package: `packages/backend/pyproject.toml`,
  `packages/frontend/package.json`, `apps/desktop/src-tauri/tauri.conf.json` +
  `Cargo.toml`. Keep them in sync (Release Please automates this).
- Conventional commits (`feat:`, `fix:`, `chore:`…) drive CHANGELOG and
  version bumps. PR titles must be conventional.

## Cutting a release

1. Merge the Release Please versioning PR (bumps versions + CHANGELOG.md).
2. Merging the release PR tags `vX.Y.Z`.
3. The `release.yml` workflow then builds, per OS:
   - Linux: AppImage + .deb + .rpm
   - Windows: NSIS installer (+ MSI)
   - macOS: DMG (universal when configured)
4. Artifacts get SHA256SUMS and are attached to a draft GitHub Release.
5. Review & publish the draft.

## Signing (when secrets are configured)

- Tauri updater key: `TAURI_SIGNING_PRIVATE_KEY` secret.
- macOS notarization: Apple Developer ID creds in secrets; skipped with a
  warning if absent.
- Windows: Azure Trusted Signing (documented in docs/releasing).

## Rules

- Never tag manually to "retrigger" — fix forward with a new commit.
- Release artifacts must come from CI builds only, never local machines.
