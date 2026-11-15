# Cross Machine and Project setup for useful coding skillls

## Strategy (IDE Specific folder)
- .claude/ contains skills for claude code environment
- .cursor/ contains skills for cursor environment
- .github/ contains skills for VS Code copilot environment


## Reusability Design
- IDE-specific folder hosts all skills needed for that specific IDE environment. 
- For self-developed skills/commands/... sharable across IDE environment, make it .claude/
- For something IDE specific, put it in their corresponding folder.
- For external skills under another (local) repo (e.g. skills), create a symlink in the IDE-specific folder.

## Using instruction
- In a new laptop/dev machine, create a symlink of "skills" -> absolute path of the corresponding IDE-specific folder.
  For example, 
  - when setting up VSCode Github copilot, create symlink at `~/.github/skills` -> `<github>/agentic-engineering/.github/skills` folder.
  - when setting up cursor, create symlink at `~/.cursor/skills` -> `<github>/agentic-engineering/.cursor/skills`
- Once this setup, all projects of the machine should becomes automatically visible.
- Do not copy or symlink skills into individual application repos; the global IDE symlink is enough.

## Matt Pocock skills (external)

Clone [mattpocock/skills](https://github.com/mattpocock/skills) as a sibling of this repo:

```bash
git clone git@github.com:mattpocock/skills.git ../skills
```

Keep Cursor/Copilot links current with the `sync-matt-skills` skill (or run its script directly):

```bash
~/.cursor/skills/sync-matt-skills/scripts/sync.sh
```

That pulls `../skills` and recreates absolute symlinks under `.cursor/skills` and `.github/skills` for every engineering + productivity skill, pruning orphans. Local skills (jira, ada-e2e-test, sync-matt-skills, …) are left alone.

## GitHub PR comments
- To fetch PR comments (`gh pr view`, `gh api …/pulls/N/comments`, or GraphQL reviewThreads), always re-run the Shell tool with `required_permissions: ["all"]` — the sandbox blocks GitHub and often surfaces as a connect/Forbidden failure.
