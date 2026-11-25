#!/usr/bin/env bash
set -euo pipefail
# npm ci must have installed the checked-in integrity-locked dependencies.
node -e 'for(const [n,v] of Object.entries({"@playwright/test":"1.65.1",playwright:"1.65.1","playwright-core":"1.65.1","axe-core":"4.11.1"})){if(require(n+"/package.json").version!==v)throw Error(n+" version mismatch")}'
git diff --exit-code -- package.json package-lock.json
