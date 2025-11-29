#!/usr/bin/env bash
# Check coding conventions

set -euo pipefail

exit_code=0

# Check for large files (>200 lines should be split)
while IFS= read -r file; do
    if [[ -f "$file" ]]; then
        lines=$(wc -l < "$file")
        if [[ $lines -gt 200 ]]; then
            echo "Warning: $file has $lines lines (consider splitting files >200 lines)"
        fi
    fi
done < <(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

exit $exit_code
