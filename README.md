# From your project root

# 0) Remove GitHub Actions (if present) and any Git metadata (including nested .git from submodules)
Remove-Item -Recurse -Force .github -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .git -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Force -Filter ".git" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 1) Start a fresh repo with 'main' as default
git init --initial-branch=main

# 2) Set your identity for this repo
git config user.name "Your Name"
git config user.email "brendakenne@situsamc.com"

# 3) Ensure Git Credential Manager is enabled (so it prompts and saves your PAT)
git config --global credential.helper manager-core
git config --global credential.useHttpPath true

# 3b) OPTIONAL: pre-store your PAT so push is non-interactive (saves to Windows Credential Manager)
# Replace <PASTE_PAT_HERE> with your actual PAT. Do this only on a trusted machine.
$creds = @"
protocol=https
host=dev.azure.com
username=brendakenne@situsamc.com
password=<PASTE_PAT_HERE>
"@
$creds | git credential-manager-core store

# 4) Commit current files as a fresh initial commit
git add -A
git commit -m "Initial import"

# 5) Add the Azure DevOps remote
git remote add origin "https://dev.azure.com/samcado/Infrastructure%20Operations/_git/Client-Uptime-Report-obs"

# 6) Push to 'main'. When prompted (if you didn’t pre-store):
#    Username: brendakenne@situsamc.com
#    Password: <your PAT>
git push -u origin main
