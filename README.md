# From your project root

# 0) (Optional) remove GitHub Actions folder if still present
Remove-Item -Recurse -Force .github -ErrorAction SilentlyContinue

# 1) Start fresh git history
Remove-Item -Recurse -Force .git -ErrorAction SilentlyContinue
git init --initial-branch=main

# 2) Commit current tree
git add -A
git commit -m "Initial import"

# 3) Point to Azure DevOps remote (HTTPS)
git remote add origin "https://dev.azure.com/samcado/Infrastructure%20Operations/_git/Client-Uptime-Report-obs"

# 4) Push as the new main branch
git push -u origin main
