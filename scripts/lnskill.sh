#!/usr/bin/env bash

set -euo pipefail

SKILL_NAME="${1:-}"

if [[ -z "$SKILL_NAME" ]]; then
	echo "Usage: $0 <skill-name>"
	exit 1
fi

# Resolve source skill directory relative to this script's repository.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="$REPO_ROOT/.claude/skills"

# Create the link in the current working repository.
DESTINATION_DIR=".claude/skills"
SOURCE_PATH="$SOURCE_DIR/$SKILL_NAME"
DESTINATION_PATH="$DESTINATION_DIR/$SKILL_NAME"

if [[ ! -e "$SOURCE_PATH" ]]; then
	echo "Skill not found: $SOURCE_PATH"
	exit 1
fi

mkdir -p "$DESTINATION_DIR"
ln -sfn "$SOURCE_PATH" "$DESTINATION_PATH"

echo "Linked $DESTINATION_PATH -> $SOURCE_PATH"
