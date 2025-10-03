git config --global credential.helper manager-core
git config --global credential.useHttpPath true

# (Optional) erase any bad/partial saved entry first
$erase = @'
protocol=https
host=dev.azure.com
'@
$erase | git credential-manager-core erase

# Store the PAT (edit the password line only)
$creds = @'
protocol=https
host=dev.azure.com
username=brendakenne@situsamc.com
password=PASTE_YOUR_PAT_HERE
'@
$creds | git credential-manager-core store




git remote remove origin 2>$null
git remote add origin "https://dev.azure.com/samcado/Infrastructure%20Operations/_git/Client-Uptime-Report-obs"
git push -u origin main            # add --force if you intend to overwrite existing history
