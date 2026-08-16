# Cross Machine and Project setup for useful coding skillls

## Strategy (IDE Specific folder)
- .claude/ contains skills for claude code environment
- .cursor/ contains skills for cursor environment
- .github/ contains skills for VS Code copilot environment


## Reusability Design
- IDE-specific folder hosts all skills needed for that specific IDE environment. 
- For self-developed skills/commands/... sharable across IDE environment, make it .claude/
- For something IDE specific, put it in their corresponding folder.
- For external skills under another (local) repo (e.g. skills), create a relative symlink in the IDE-specific.

## Using instruction
- In a new laptop/dev machine, create a symlink of "skills" -> absolute path of the corresponding IDE-specific folder.
  For example, 
  - when setting up VSCode Github copilot, create symlink at `~/.github/skills` -> `<github>/agentic-engineering/.github/skills` folder.
  - when setting up cursor, create symlink at `~/.cursor/skills` -> `<github>/agentic-engineering/.cursor/skills`
- Once this setup, all projects of the machine should becomes automatically visible.

