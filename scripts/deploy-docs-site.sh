#!/usr/bin/env bash
# Deploy the built VitePress dist to the production docs host (doc.oouo.top).
#
# Topology: the host Caddy serves /opt/lumirss-docs/current (a symlink);
# each deploy lands in releases/<ts>/ and the symlink flips atomically,
# so the site never serves a half-synced tree. Caddy site block (hand-
# managed, BEGIN/END LUMIRSS docs-site markers) needs no reload — static
# files take effect immediately.
#
# Required env:
#   DOCS_DEPLOY_HOST          target host (e.g. 47.100.64.202)
#   DOCS_DEPLOY_USER          ssh user (dedicated low-priv 'docs-deploy')
#   DOCS_DEPLOY_KEY           path to the deploy private key
#   DOCS_DEPLOY_KNOWN_HOSTS   path to pinned known_hosts
# Optional env:
#   DIST_DIR                  local dist to deploy (default docs/.vitepress/dist)
#   REMOTE_ROOT               server dir (default /opt/lumirss-docs)
#   KEEP_RELEASES             old releases to keep (default 5)
#
# Usage: scripts/deploy-docs-site.sh
set -euo pipefail

: "${DOCS_DEPLOY_HOST:?DOCS_DEPLOY_HOST is required}"
: "${DOCS_DEPLOY_USER:?DOCS_DEPLOY_USER is required}"
: "${DOCS_DEPLOY_KEY:?DOCS_DEPLOY_KEY is required}"
: "${DOCS_DEPLOY_KNOWN_HOSTS:?DOCS_DEPLOY_KNOWN_HOSTS is required}"

DIST_DIR="${DIST_DIR:-docs/.vitepress/dist}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/lumirss-docs}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

[ -f "$DIST_DIR/index.html" ] || { echo "FAIL: $DIST_DIR/index.html missing (run npm run docs:build first)"; exit 1; }

SSH_OPTS=(-i "$DOCS_DEPLOY_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$DOCS_DEPLOY_KNOWN_HOSTS")
REMOTE="$DOCS_DEPLOY_USER@$DOCS_DEPLOY_HOST"

echo "==> rsync dist -> $REMOTE:$REMOTE_ROOT/releases/$STAMP/"
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$REMOTE_ROOT/releases/$STAMP'"
rsync -a --delete \
  -e "ssh -i $DOCS_DEPLOY_KEY -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$DOCS_DEPLOY_KNOWN_HOSTS" \
  "$DIST_DIR/" "$REMOTE:$REMOTE_ROOT/releases/$STAMP/"

echo "==> atomic symlink flip: current -> releases/$STAMP"
ssh "${SSH_OPTS[@]}" "$REMOTE" "set -e
  ln -sfn 'releases/$STAMP' '$REMOTE_ROOT/.current.tmp'
  mv -Tf '$REMOTE_ROOT/.current.tmp' '$REMOTE_ROOT/current'
  # prune old releases, keep the newest $KEEP_RELEASES
  ls -1dt '$REMOTE_ROOT'/releases/*/ | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf
  echo \"deployed: \$(readlink '$REMOTE_ROOT/current')\"
"
echo "==> OK: https://doc.oouo.top/ now serves release $STAMP"
