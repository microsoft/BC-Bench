# Creating Git Tag v0.1.0

## Quick Guide: Creating the Tag

To create the `v0.1.0` tag at the current head of the main branch, follow these steps:

### Option 1: Using Git CLI (Recommended)

```bash
# 1. Ensure you're on the main branch
git checkout main

# 2. Pull the latest changes
git pull origin main

# 3. Create an annotated tag (recommended for releases)
git tag -a v0.1.0 -m "Release v0.1.0 - Pre-refactoring snapshot"

# 4. Push the tag to the remote repository
git push origin v0.1.0
```

### Option 2: Using GitHub Web Interface

1. Go to https://github.com/microsoft/BC-Bench/releases
2. Click "Create a new release"
3. Click "Choose a tag" and type `v0.1.0`
4. Select "Create new tag: v0.1.0 on publish"
5. Target: `main` branch
6. Release title: `v0.1.0 - Pre-refactoring snapshot`
7. Description: Add notes about the state of the repository
8. Click "Publish release"

This will automatically create the tag and a GitHub release.

### Option 3: Using GitHub CLI

```bash
# Create a release with a tag
gh release create v0.1.0 --title "v0.1.0 - Pre-refactoring snapshot" --notes "Repository state before major refactoring"
```

## Alternative Approaches for Preserving State

While tags are a good option, here are alternatives to consider:

### 1. **Feature Branch** (Recommended for Active Work)
```bash
# Create a branch from main before starting refactoring
git checkout main
git pull
git checkout -b pre-refactoring-state
git push -u origin pre-refactoring-state
```

**Pros:**
- Can continue to commit to this branch if needed
- Easy to create PRs from this state
- More flexible than tags

**Cons:**
- Branches can be accidentally deleted
- Takes up more space if you create many

### 2. **Git Tag** (Recommended for Snapshots)
This is what you originally requested. Tags are:

**Pros:**
- Immutable reference points
- Standard way to mark releases/milestones
- Semantic versioning compatible (v0.1.0)
- Lightweight and don't clutter branch list

**Cons:**
- Cannot be modified (this is usually a pro)
- Requires a separate command to push

### 3. **GitHub Release**
Creates both a tag and a release with release notes.

**Pros:**
- Includes tag automatically
- Provides downloadable source archives
- Visible in the Releases section
- Can add release notes and assets

**Cons:**
- More visible/formal than just a tag
- Might imply a "release" when it's just a snapshot

### 4. **Backup Branch**
```bash
git checkout main
git branch backup-before-refactoring-2025-10-25
git push origin backup-before-refactoring-2025-10-25
```

**Pros:**
- Clear naming with date
- Easy to find and reference
- Can be deleted later when no longer needed

**Cons:**
- Not semantically versioned
- Can clutter branch list

## Recommendation

For your use case (saving state before a big refactoring), I recommend **creating an annotated tag** (Option 1):

```bash
git checkout main
git pull origin main
git tag -a v0.1.0 -m "Pre-refactoring snapshot - $(date '+%Y-%m-%d')"
git push origin v0.1.0
```

This is because:
1. ✅ Immutable - won't accidentally change
2. ✅ Standard practice for version markers
3. ✅ Easy to checkout: `git checkout v0.1.0`
4. ✅ Compatible with semantic versioning
5. ✅ Can be used as a base for comparing changes

## Verifying the Tag

After creating the tag:

```bash
# List all tags
git tag

# Show tag details
git show v0.1.0

# Checkout the tag (creates detached HEAD)
git checkout v0.1.0

# Create a branch from the tag if needed
git checkout -b fix-from-v0.1.0 v0.1.0
```

## Reverting to the Tagged State

If you need to go back to this state:

```bash
# Option 1: Create a new branch from the tag
git checkout -b revert-to-v0.1.0 v0.1.0

# Option 2: Reset main to the tag (DESTRUCTIVE - use with caution)
git checkout main
git reset --hard v0.1.0
git push --force origin main  # Only if you really need to rewrite history

# Option 3: Revert commits (safer, preserves history)
git checkout main
git revert <commit-range>
```

## Best Practices

1. **Use annotated tags for versions**: `git tag -a v0.1.0 -m "message"`
2. **Use lightweight tags for temporary markers**: `git tag temp-marker`
3. **Follow semantic versioning**: v{MAJOR}.{MINOR}.{PATCH}
4. **Include meaningful messages** in annotated tags
5. **Push tags explicitly**: `git push origin v0.1.0` or `git push --tags`

## Semantic Versioning Guide

- `v0.1.0` - Good for pre-1.0 development
- `v1.0.0` - First stable release
- `v1.1.0` - New features (minor version)
- `v1.1.1` - Bug fixes (patch version)
- `v2.0.0` - Breaking changes (major version)
