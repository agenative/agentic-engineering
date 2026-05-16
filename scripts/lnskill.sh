#! /bin/bash

SKILL_NAME=$1

# Define the source and destination directories
SOURCE_DIR="~/Documents/Github/agentic-engineering/.claude/skills"
DESTINATION_DIR=".claude/skills"


# Create a symbolic link
mkdir -p $DESTINATION_DIR
ln -s ~/Documents/Github/agentic-engineering/.claude/skills/$SKILL_NAME $DESTINATION_DIR/$SKILL_NAME
