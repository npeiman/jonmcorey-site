#!/usr/bin/env bash
#
# publish.sh — push the repo to GitHub and deploy it to the live server.
#
# Live target: jonmcorey.com (srv002 / 100.92.154.76)
#   code: /opt/pag/website      (plain file copy, NOT a git checkout)
#   data: /opt/pag/data/pag.db  (lives outside the code dir; never overwritten)
#
# Usage:
#   ./deploy/publish.sh                 # commit (if needed), push, deploy, verify
#   ./deploy/publish.sh --dry-run       # show what would change; change nothing
#   ./deploy/publish.sh -m "message"    # use this commit message
#   ./deploy/publish.sh --skip-git      # deploy only, no commit/push
#
# Safe by design:
#   * never copies pag.db, .git, server.log, __pycache__ or .DS_Store
#   * restores pag:pag ownership after rsync runs as root
#   * verifies the live site returns HTTP 200 before reporting success
#
set -Eeuo pipefail

# ---------------------------------------------------------------- settings
REMOTE_HOST="${REMOTE_HOST:-100.92.154.76}"
REMOTE_PATH="${REMOTE_PATH:-/opt/pag/website}"
SERVICE="${SERVICE:-pag}"
PUBLIC_URL="${PUBLIC_URL:-https://jonmcorey.com/}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
SKIP_GIT=0
COMMIT_MSG="Update site content"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)  DRY_RUN=1; shift ;;
    --skip-git) SKIP_GIT=1; shift ;;
    -m|--message) COMMIT_MSG="${2:?missing commit message}"; shift 2 ;;
    -h|--help)  awk 'NR>1 && /^set -Eeuo/{exit} NR>1' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '    \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

trap 'die "failed at line $LINENO"' ERR

# ---------------------------------------------------------------- preflight
say "Preflight"
[[ -f server.py ]] || die "server.py not found — are you in the website repo?"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not a git repository"
ok "repo: $REPO_ROOT"

if ! ssh -o ConnectTimeout=8 -o BatchMode=yes "root@${REMOTE_HOST}" true 2>/dev/null; then
  die "cannot SSH to root@${REMOTE_HOST} — check the connection first"
fi
ok "ssh reachable: root@${REMOTE_HOST}"

[[ $DRY_RUN -eq 1 ]] && say "DRY RUN — nothing will be changed"

# ---------------------------------------------------------------- git
if [[ $SKIP_GIT -eq 0 ]]; then
  say "Git: commit and push"
  if [[ -n "$(git status --porcelain)" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
      warn "uncommitted changes present:"
      git status --short | sed 's/^/      /'
    else
      git add -A
      git commit -m "$COMMIT_MSG"
      ok "committed: $COMMIT_MSG"
    fi
  else
    ok "working tree clean — nothing to commit"
  fi

  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  if [[ $DRY_RUN -eq 1 ]]; then
    warn "would run: git push origin $BRANCH"
  else
    git push origin "$BRANCH"
    ok "pushed to origin/$BRANCH"
  fi
else
  say "Git: skipped (--skip-git)"
fi

# ---------------------------------------------------------------- deploy
say "Deploy to ${REMOTE_HOST}:${REMOTE_PATH}"
RSYNC_ARGS=(
  -avz
  --no-owner --no-group
  --delete
  --exclude '.git'
  --exclude 'pag.db'
  --exclude '*.db'
  --exclude 'server.log'
  --exclude '__pycache__'
  --exclude '.DS_Store'
)
[[ $DRY_RUN -eq 1 ]] && RSYNC_ARGS+=(--dry-run --itemize-changes)

rsync "${RSYNC_ARGS[@]}" ./ "root@${REMOTE_HOST}:${REMOTE_PATH}/"
ok "files transferred"

if [[ $DRY_RUN -eq 1 ]]; then
  warn "dry run complete — no changes made"
  exit 0
fi

say "Fix ownership"
ssh "root@${REMOTE_HOST}" "chown -R pag:pag ${REMOTE_PATH}"
ok "owner restored to pag:pag"

# ---------------------------------------------------------------- restart
say "Restart service: ${SERVICE}"
ssh "root@${REMOTE_HOST}" "systemctl restart ${SERVICE} && sleep 2 && systemctl is-active ${SERVICE}"
ok "service ${SERVICE} is active"

# ---------------------------------------------------------------- verify
say "Verify live site"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$PUBLIC_URL" || echo 000)"
if [[ "$CODE" == "200" ]]; then
  ok "${PUBLIC_URL} → HTTP 200"
else
  die "${PUBLIC_URL} → HTTP ${CODE}"
fi

if curl -s -m 15 "$PUBLIC_URL" | grep -qi '<title>'; then
  ok "page title: $(curl -s -m 15 "$PUBLIC_URL" | grep -oiE '<title>[^<]*</title>' | head -1)"
fi

say "Done — ${PUBLIC_URL} is live"
echo "    code:     ${REMOTE_PATH}"
echo "    database: /opt/pag/data/pag.db (untouched)"
