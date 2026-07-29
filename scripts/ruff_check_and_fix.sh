#!/bin/bash

uv run ruff check --fix .
check_status=$?

uv run ruff format .

if [ $check_status -ne 0 ]; then
    echo "Unfixable lint violations remain."
    exit 1
fi