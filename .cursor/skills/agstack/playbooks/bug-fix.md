# Bug Fix

1. Start an isolated local environments for the task.
   - Reuse an available local environment or start a new environment locally.
   - Reuse the environment only if it carries the correct branch/worktree. Otherwise, remove the existing and restart in the correct branch/worktree. 
   - Do not rely on any available make command but the typical init_environments and doco. 

2. Reproduce the reported defect.
   Capture the failing behavior or test output.

3. Investigate the root cause.
   Examine relevant code and runtime evidence.
   Confirm the cause before changing code.

4. Implement the smallest correction that
   addresses the confirmed root cause.
   Avoid unrelated refactoring.

5. Verify the correction.
   Re-run the original reproduction and
   relevant regression tests.

6. Review the changes.
   Check for unnecessary modifications,
   regressions, and incomplete fixes.

7. Report the root cause, correction,
   and verification evidence.

8. Submit the fix.
