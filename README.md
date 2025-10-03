# From project root

# 1) Remove GitHub config and pipelines
Remove-Item -Recurse -Force .github -ErrorAction SilentlyContinue

# 2) Remove other GitHub-specific metadata (optional)
Remove-Item -Force .gitmodules,.gitreview,.mailmap -ErrorAction SilentlyContinue

# 3) Drop LFS attrs lines (optional)
if (Test-Path .gitattributes) {
  (Get-Content .gitattributes) | Where-Object {$_ -notmatch 'filter=lfs'} | Set-Content .gitattributes
}

# 4) Quick scrub for old URLs/emails/tokens (review results)
Select-String -Path .\* -Pattern 'github\.com/|ghp_[A-Za-z0-9]{36}|AKIA[0-9A-Z]{16}|your@personal\.com|YourName' -AllMatches -List

# 5) Nuke old Git history and re-init fresh
Remove-Item -Recurse -Force .git -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Force -Filter ".git" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

git init --initial-branch=main
git config user.name "Your Name"
git config user.email "your@company.com"

git add -A
git commit -m "Initial import (cleaned: removed .github/workflows and metadata)"
git remote add origin <COMPANY_REPO_URL>
git push -u origin main
