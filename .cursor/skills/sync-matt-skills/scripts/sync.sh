#!/usr/bin/env bash
# Pull mattpocock/skills and resync symlinks into agentic-engineering IDE skill folders.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# .../agentic-engineering/.cursor/skills/sync-matt-skills/scripts
AE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SKILLS_ROOT="$(cd "$AE_ROOT/../skills" && pwd)"

TARGETS=()
SYNC_CURSOR=1
SYNC_GITHUB=1
SKIP_PULL=0

usage() {
	cat <<'USAGE'
Usage: sync.sh [--cursor-only | --github-only] [--skip-pull]

  Pulls ../skills (mattpocock/skills) and recreates absolute symlinks for every
  engineering + productivity skill into:
    agentic-engineering/.cursor/skills
    agentic-engineering/.github/skills

  Local skills (real directories) and non-mattpocock symlinks are left alone.
  Orphan mattpocock links (removed/renamed upstream) are deleted.
USAGE
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--cursor-only) SYNC_GITHUB=0 ;;
		--github-only) SYNC_CURSOR=0 ;;
		--skip-pull) SKIP_PULL=1 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
	esac
	shift
done

[[ "$SYNC_CURSOR" -eq 1 ]] && TARGETS+=("$AE_ROOT/.cursor/skills")
[[ "$SYNC_GITHUB" -eq 1 ]] && TARGETS+=("$AE_ROOT/.github/skills")

if [[ ! -d "$SKILLS_ROOT/skills/engineering" || ! -d "$SKILLS_ROOT/skills/productivity" ]]; then
	echo "mattpocock skills not found at: $SKILLS_ROOT" >&2
	echo "Clone first: git clone git@github.com:mattpocock/skills.git \"$AE_ROOT/../skills\"" >&2
	exit 1
fi

if [[ "$SKIP_PULL" -eq 0 ]]; then
	echo "Pulling $SKILLS_ROOT ..."
	git -C "$SKILLS_ROOT" pull --ff-only
	echo "HEAD: $(git -C "$SKILLS_ROOT" log -1 --oneline)"
else
	echo "Skipping pull (--skip-pull)"
fi

is_mattpocock_link() {
	local path="$1"
	[[ -L "$path" ]] || return 1
	local target
	target="$(readlink "$path")"
	# Absolute or relative targets that resolve under SKILLS_ROOT
	case "$target" in
		"$SKILLS_ROOT"/*) return 0 ;;
	esac
	if [[ -e "$path" ]]; then
		local resolved
		resolved="$(cd "$path" && pwd -P 2>/dev/null || true)"
		[[ -n "$resolved" && "$resolved" == "$SKILLS_ROOT"/* ]] && return 0
	fi
	return 1
}

link_category_into() {
	local dest="$1"
	local category="$2"
	local category_dir="$SKILLS_ROOT/skills/$category"
	local source_path skill_name destination_path

	mkdir -p "$dest"
	for source_path in "$category_dir"/*/; do
		[[ -d "$source_path" ]] || continue
		skill_name="$(basename "$source_path")"
		source_path="$(cd "$source_path" && pwd)"
		destination_path="$dest/$skill_name"

		if [[ -e "$destination_path" && ! -L "$destination_path" ]]; then
			echo "SKIP  $destination_path (local directory, not overwriting)"
			continue
		fi

		ln -sfn "$source_path" "$destination_path"
		echo "LINK  $destination_path -> $source_path"
	done
}

prune_orphans_in() {
	local dest="$1"
	local entry name target resolved keep

	[[ -d "$dest" ]] || return 0

	for entry in "$dest"/*; do
		[[ -e "$entry" || -L "$entry" ]] || continue
		is_mattpocock_link "$entry" || continue

		name="$(basename "$entry")"
		keep=0
		if [[ -d "$SKILLS_ROOT/skills/engineering/$name" || -d "$SKILLS_ROOT/skills/productivity/$name" ]]; then
			keep=1
		fi

		if [[ "$keep" -eq 0 ]]; then
			rm "$entry"
			echo "PRUNE $entry (no longer upstream)"
		fi
	done
}

for dest in "${TARGETS[@]}"; do
	echo "--- syncing $dest ---"
	link_category_into "$dest" engineering
	link_category_into "$dest" productivity
	prune_orphans_in "$dest"
done

echo "Done."
