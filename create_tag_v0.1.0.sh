#!/bin/bash
# Helper script to create v0.1.0 tag on the main branch
# 
# This script will:
# 1. Ensure you're on the main branch
# 2. Pull the latest changes
# 3. Create an annotated tag v0.1.0
# 4. Push the tag to the remote repository
#
# Usage: ./create_tag_v0.1.0.sh

set -e  # Exit on error

echo "🏷️  Creating tag v0.1.0 on main branch..."
echo ""

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Error: Not in a git repository"
    exit 1
fi

# Check if tag already exists locally
if git rev-parse v0.1.0 >/dev/null 2>&1; then
    echo "⚠️  Warning: Tag v0.1.0 already exists locally"
    echo ""
    echo "Existing tag information:"
    git show v0.1.0 --no-patch
    echo ""
    read -p "Do you want to delete and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git tag -d v0.1.0
        echo "✅ Local tag deleted"
    else
        echo "❌ Aborted"
        exit 1
    fi
fi

# Save current branch
CURRENT_BRANCH=$(git branch --show-current)
echo "📍 Current branch: $CURRENT_BRANCH"

# Checkout main branch
echo "🔄 Switching to main branch..."
if ! git checkout main; then
    echo "❌ Error: Could not checkout main branch"
    echo "   Make sure the main branch exists"
    exit 1
fi

# Pull latest changes
echo "⬇️  Pulling latest changes from origin..."
if ! git pull origin main; then
    echo "❌ Error: Could not pull from origin/main"
    echo "   Continuing anyway..."
fi

# Get current commit
COMMIT_SHA=$(git rev-parse HEAD)
COMMIT_MSG=$(git log -1 --pretty=format:"%s")
echo ""
echo "📌 Current HEAD commit:"
echo "   SHA: $COMMIT_SHA"
echo "   Message: $COMMIT_MSG"
echo ""

# Create annotated tag
TAG_MESSAGE="Pre-refactoring snapshot - Created on $(date '+%Y-%m-%d %H:%M:%S')"
echo "✨ Creating annotated tag v0.1.0..."
git tag -a v0.1.0 -m "$TAG_MESSAGE"
echo "✅ Tag created successfully"

# Show tag info
echo ""
echo "📋 Tag information:"
git show v0.1.0 --no-patch

# Confirm before pushing
echo ""
read -p "Push tag v0.1.0 to origin? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "⬆️  Pushing tag to origin..."
    if git push origin v0.1.0; then
        echo "✅ Tag pushed successfully!"
        echo ""
        echo "🎉 Tag v0.1.0 has been created and pushed to origin"
        echo "   You can now start your refactoring with confidence!"
        echo ""
        echo "To view the tag:"
        echo "   git show v0.1.0"
        echo ""
        echo "To checkout the tag:"
        echo "   git checkout v0.1.0"
        echo ""
        echo "To create a branch from the tag:"
        echo "   git checkout -b my-branch v0.1.0"
    else
        echo "❌ Error: Could not push tag to origin"
        echo "   The tag has been created locally but not pushed"
        exit 1
    fi
else
    echo "ℹ️  Tag created locally but not pushed"
    echo "   To push later: git push origin v0.1.0"
fi

# Return to original branch if it wasn't main
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo ""
    echo "🔄 Returning to branch: $CURRENT_BRANCH"
    git checkout "$CURRENT_BRANCH"
fi

echo ""
echo "✨ Done!"
