#! /bin/bash

RULE_NAME=$1

# Define the source and destination directories
SOURCE_DIR="~/Documents/git/agentic-engineering/.cursor/rules"
DESTINATION_DIR=".cursor/rules"


# Create a symbolic link
mkdir -p $DESTINATION_DIR
ln -s ~/Documents/git/agentic-engineering/.cursor/rules/$RULE_NAME.mdc $DESTINATION_DIR/$RULE_NAME.mdc
