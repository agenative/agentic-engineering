#!/usr/bin/env bash

set -euo pipefail

SKILL_NAMES=("$@")

if [[ ${#SKILL_NAMES[@]} -eq 0 ]]; then
	echo "Usage: $0 <skill-name> [<skill-name> ...]"
	exit 1
fi

# Resolve source skills directory from external skills repo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXTERNAL_SKILLS_DIR="$REPO_ROOT/../skills/skills/productivity"

# Target directory in this repository
DESTINATION_DIR="$REPO_ROOT/.github/skills"

if [[ ! -d "$EXTERNAL_SKILLS_DIR" ]]; then
	echo "External skills directory not found: $EXTERNAL_SKILLS_DIR"
	exit 1
fi

mkdir -p "$DESTINATION_DIR"

for SKILL_NAME in "${SKILL_NAMES[@]}"; do
	SOURCE_PATH="$EXTERNAL_SKILLS_DIR/$SKILL_NAME"
	DESTINATION_PATH="$DESTINATION_DIR/$SKILL_NAME"

	if [[ ! -e "$SOURCE_PATH" ]]; then
		echo "Skill not found: $SOURCE_PATH"
		exit 1
	fi

	ln -sfn "$SOURCE_PATH" "$DESTINATION_PATH"
	echo "Linked $DESTINATION_PATH -> $SOURCE_PATH"
done
