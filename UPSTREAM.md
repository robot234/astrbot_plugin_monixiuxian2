# Upstream and snapshot notes

- Upstream: `xiaojuwa/astrbot_plugin_monixiuxian2`
- Snapshot time (UTC): `2026-08-29T07:52:44Z`
- Source path: `/AstrBot/data/plugins/astrbot_plugin_monixiuxian2` inside the `astrbot` Docker container on the Raspberry Pi host
- Plugin version: `v3.1.4.11`
- License: `AGPL-3.0`
- Snapshot scope: the published plugin source and release resources only

The source directory contained an old unusable Git directory with no reliable history. This backup therefore does not claim an upstream commit or commit provenance.

Runtime data, databases, local configuration state, caches, logs, secrets, and the store backup area were intentionally excluded. In particular, plugin runtime data outside this package and `/AstrBot/data/plugin_backups` are not part of this snapshot.
