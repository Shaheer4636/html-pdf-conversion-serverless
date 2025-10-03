# From your project root

# 0) (optional) ensure GitHub Actions are gone
rm -rf .github

# 1) Start fresh history if you haven't already
rm -rf .git
git init --initial-branch=main

# 2) Set your identity for this repo
git config user.name "Your Name"
git config user.email "brendakenne@situsamc.com"

# 3) Ensure Git Credential Manager (GCM) will prompt and save
git config --global credential.helper manager-core
git config --global credential.useHttpPath true

# 4) Commit and add Azure DevOps remote
git add -A
git commit -m "Initial import"
git remote add origin "https://dev.azure.com/samcado/Infrastructure%20Operations/_git/Client-Uptime-Report-obs"

# 5) Push. When prompted:
#    Username: brendakenne@situsamc.com
#    Password: <your PAT>
git push -u origin main
