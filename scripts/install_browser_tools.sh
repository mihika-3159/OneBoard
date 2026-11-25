#!/usr/bin/env bash
# Keep the application lock untouched. Playwright's published packages declare
# exact versions of their runtime dependencies; verify the installed identities.
set -euo pipefail
version=1.65.1
npm install --no-save --package-lock=false --ignore-scripts --no-audit --no-fund "@playwright/test@$version"
node -e 'for (const n of ["@playwright/test","playwright","playwright-core"]) { const p=require(n+"/package.json"); if(p.version!==process.argv[1]) throw Error(n+" version mismatch"); }' "$version"
git diff --exit-code -- package.json package-lock.json
