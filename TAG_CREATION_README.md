# Creating Git Tag v0.1.0 - Implementation Guide

## Summary

This PR provides tools and documentation for creating a git tag `v0.1.0` at the current head of the main branch. Due to environment limitations, the actual tag creation must be performed manually or by running the provided script.

## Quick Start

### Option 1: Run the Helper Script (Easiest)

```bash
./create_tag_v0.1.0.sh
```

This interactive script will:
- ✅ Switch to the main branch
- ✅ Pull the latest changes
- ✅ Create an annotated tag `v0.1.0`
- ✅ Push it to the remote repository
- ✅ Return you to your original branch

### Option 2: Manual Command (Quick)

```bash
git checkout main
git pull origin main
git tag -a v0.1.0 -m "Pre-refactoring snapshot - $(date '+%Y-%m-%d')"
git push origin v0.1.0
```

### Option 3: GitHub Web Interface (No CLI needed)

1. Visit: https://github.com/microsoft/BC-Bench/releases/new
2. Type `v0.1.0` in "Choose a tag"
3. Select "Create new tag: v0.1.0 on publish"
4. Set target to `main` branch
5. Add title: "v0.1.0 - Pre-refactoring snapshot"
6. Click "Publish release"

## Why Tags Are Good for Your Use Case

You mentioned wanting to save the state before a big refactoring. Tags are **perfect** for this because:

1. **Immutable** - Once created, they won't change accidentally
2. **Lightweight** - Just a pointer to a commit, no extra storage
3. **Standard Practice** - Used industry-wide for marking important points
4. **Easy to Reference** - `git checkout v0.1.0` works anywhere
5. **Semantic Versioning** - v0.1.0 follows standard versioning

## Alternative Approaches Considered

### 1. Feature Branch
```bash
git checkout main
git checkout -b pre-refactoring-backup
git push -u origin pre-refactoring-backup
```
**When to use:** If you might want to make more commits to this state

### 2. Backup Branch with Date
```bash
git branch backup-2025-10-25
git push origin backup-2025-10-25
```
**When to use:** For temporary backups you'll delete later

### 3. GitHub Release
Use the GitHub web interface to create a release
**When to use:** When you want more visibility and can include release notes

## Recommendation

✅ **Use the git tag approach** (Option 1 or 2) because:
- It matches semantic versioning best practices
- It's immutable and safe
- It's the standard way to mark repository states
- You can easily reference it later (`v0.1.0` is cleaner than a branch name)

## Verifying the Tag After Creation

```bash
# List all tags
git tag

# Show tag details
git show v0.1.0

# List tags with dates
git tag -l --format='%(refname:short) %(creatordate:short) %(subject)'
```

## Using the Tag Later

### To view the code at that point:
```bash
git checkout v0.1.0
```

### To create a new branch from the tag:
```bash
git checkout -b hotfix-from-v0.1.0 v0.1.0
```

### To compare current code with the tag:
```bash
git diff v0.1.0..HEAD
```

### To see commits since the tag:
```bash
git log v0.1.0..HEAD --oneline
```

## Files in This PR

1. **`create_tag_v0.1.0.sh`** - Interactive helper script to create and push the tag
2. **`TAGGING_GUIDE.md`** - Comprehensive guide to git tags and alternatives
3. **`TAG_CREATION_README.md`** - This file, quick reference guide

## Important Notes

⚠️ **This PR does not automatically create the tag** because:
- Tags are repository metadata, not file changes
- They require special permissions to push to the repository
- It's safer to let you review and create it manually

The tag must be created by someone with write access to the repository using one of the methods above.

## Next Steps

1. Review this PR
2. Merge this PR to get the helper script and documentation into the repository
3. Run `./create_tag_v0.1.0.sh` from the main branch
4. Start your refactoring with confidence! 🚀

## Questions?

- **Can I create multiple tags?** Yes! You can create v0.1.1, v0.2.0, etc.
- **Can I delete a tag?** Yes, but be careful:
  - Local: `git tag -d v0.1.0`
  - Remote: `git push origin --delete v0.1.0`
- **What if the tag already exists?** The script will ask if you want to replace it
- **Can I move a tag?** Not recommended, but possible by deleting and recreating it

## Learn More

See `TAGGING_GUIDE.md` for detailed information about:
- Git tag best practices
- Semantic versioning
- Alternative approaches
- Advanced tag operations
