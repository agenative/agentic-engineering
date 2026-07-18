#! /bin/bash

# ln mattpocock skills
SKILL_CAT=$1
SKILL_NAME=$2

SOURCE_DIR="$HOME/Github/skills/skills"
DESTINATION_DIR=".claude/skills"
SOURCE_PATH="$SOURCE_DIR/$SKILL_CAT/$SKILL_NAME"
LINK_PATH="$DESTINATION_DIR/$SKILL_NAME"

mkdir -p "$DESTINATION_DIR"
ln -sfn "$SOURCE_PATH" "$LINK_PATH"
