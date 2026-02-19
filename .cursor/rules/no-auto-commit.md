# Git Commit and Push Policy

## Rule: Never Commit or Push Without Explicit User Direction

**Applies to:** All git operations that modify repository state

### Policy

1. **DO NOT** run `git commit` unless explicitly asked by the user
2. **DO NOT** run `git push` unless explicitly asked by the user
3. **DO NOT** run `git add` and commit in a single operation without permission
4. **DO** stage files with `git add` when preparing for a user-requested commit
5. **DO** run readonly git commands (`git status`, `git diff`, `git log`) freely

### What Requires Permission

❌ **Never do without being asked:**
- `git commit`
- `git push`
- `git commit --amend`
- `git rebase`
- `git merge` (unless resolving a conflict the user initiated)
- Any operation that modifies commit history
- Any operation that sends data to remote

✅ **OK to do without permission:**
- `git status`
- `git diff`
- `git log`
- `git show`
- `git branch -a` (list branches)
- `git remote -v` (list remotes)
- Other readonly inspection commands

### How to Handle Commit Requests

When the user says "commit" or "commit and push":

1. **Prepare the commit:**
   - Run `git status` and `git diff` to see changes
   - Stage appropriate files with `git add`
   - Review what will be committed

2. **Create a good commit message:**
   - Follow repository conventions
   - Be descriptive about what changed
   - Include context about why

3. **Execute the commit:**
   - Run `git commit` with the message
   - Verify success with `git status`

4. **Push only if explicitly requested:**
   - If user said "commit and push", then push
   - If user only said "commit", stop after committing
   - Always confirm push succeeded

### Examples

**User says:** "Make these changes"
- ✅ Make the changes
- ❌ Don't commit automatically

**User says:** "Fix the bug and commit"
- ✅ Fix the bug
- ✅ Stage and commit with good message
- ❌ Don't push unless also requested

**User says:** "Commit and push"
- ✅ Stage changes
- ✅ Create commit
- ✅ Push to remote
- ✅ Verify success

**User says:** "Push my changes"
- ✅ Push (assumes commits already exist)
- ❌ Don't create new commits first

### Rationale

- User maintains control over repository state
- Prevents unwanted commits cluttering history
- Allows user to review changes before they're permanent
- User decides when work is ready to share (push)
- Reduces risk of committing incomplete or incorrect changes
