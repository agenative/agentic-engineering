# Remove feature

1. Review the removal scope from the Jira ticket.
   Use the `jira` skill to fetch the ticket bundle.
   List what must be removed and what must keep working.

2. Confirm the scope against the codebase.
   Trace every reference to the feature: code, config, schemas, tests, docs.
   Identify the impacted paths that must keep working after removal.
   Record any mismatch with the ticket's stated scope.

3. Clarify the removal boundary.
   Use the `grill-me` skill to resolve what is removed versus kept,
   open design questions, and side effects on dependent paths.
   Do not proceed while any boundary or side effect is unresolved.

4. Write tests for the impacted paths.
   Use the `tdd` skill.
   Cover only the paths that must keep working, plus assertions that the removed behavior is gone.

5. Run the tests before removal.
   Tests for the impacted paths must pass.
   Fix the tests, not production code, if they fail.

6. Implement the removal.
   Remove only what the confirmed scope covers.
   Avoid unrelated refactoring.

7. Run the tests again after removal.
   All impacted path tests and relevant regression tests must pass.

8. Review the changes.
   Check for leftover references, unnecessary modifications, and regressions.

9. Submit the removal using the Cursor `submit` command.
