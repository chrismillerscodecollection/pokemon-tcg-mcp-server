#!/bin/bash

set -e

git add .

if git diff --cached --quiet; then
    echo "Nothing staged to commit."
    exit 0
fi

read -p "Enter your commit message: " message
git commit -m "$message"
git pull
if ! git diff --check --quiet; then
    echo "Merge conflict detected. Resolve manually before pushing."
    exit 1
fi
git push