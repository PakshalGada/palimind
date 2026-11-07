# Third-party licences

Palimind bundles the following third-party components in addition to the
JavaScript/Python dependencies recorded in their lockfiles.

## agent-desktop (vendored source)

- Project: agent-desktop
- Version: v1.1.0 (commit `17467da5142d471b1e3a6b24828a5d3ad4d8c547`)
- Vendored path: `packages/desktop-native/vendor/agent-desktop/`
- Used crates: `crates/core` (unmodified), `crates/linux` (modified)
- Licence: Apache License 2.0
- Copyright: the agent-desktop contributors

The upstream `LICENSE` and a `NOTICE` describing local modifications are in
`packages/desktop-native/`. Modified files carry `// Palimind:` markers, and
the full local delta is in
`packages/desktop-native/patches/0001-atspi44-compat.patch`.

Apache-2.0 is compatible with Palimind's MIT licence: the vendored files stay
under Apache-2.0, the NOTICE is retained, and distributions include this file
and `packages/desktop-native/NOTICE`.
