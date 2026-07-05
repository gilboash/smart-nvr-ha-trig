#!/usr/bin/env bash
# Usage: ./scripts/bump.sh [message]
# Increments the patch version in VERSION, commits everything staged + VERSION, and pushes.
set -euo pipefail
cd "$(dirname "$0")/.."

current=$(cat VERSION | tr -d '[:space:]')
major="${current%%.*}"; rest="${current#*.}"
minor="${rest%%.*}"; patch="${rest#*.}"
next="${major}.${minor}.$((patch + 1))"

echo "$next" > VERSION
echo "Bumping $current → $next"

msg="${1:-"bump version to $next"}"
git add VERSION
git commit -m "$msg

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push origin main
