# Release documentation

This folder holds the release gate evidence and user-facing notes for the
current hardening cycle.

- [Phase 11 hardening](./phase-11-hardening.md)
- [Phase 11 release notes](./phase-11-release-notes.md)

## Release gate

A release candidate must pass:

1. `npm run build --prefix packages/frontend`
2. `npm test --prefix packages/frontend`
3. `cd packages/backend && python -m pytest -m "not integration"`
4. `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml`
5. `npm audit --omit=dev --prefix packages/frontend`
6. Responsive QA at 390 / 768 / 1024 / 1440 px
7. Accessibility audit across Chat, Workbench, Chat dialogs, Skill Manager,
   Data Mode and Quick Ask
8. Multimodal path checks for image, audio and video tools

The release workflow itself (tagging, installers, signing) is documented in
`skills/release/SKILL.md` and `.github/workflows/release.yml`.
