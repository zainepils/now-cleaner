$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$output = 'dist/windows-release'
New-Item -ItemType Directory -Force $output | Out-Null
$compiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
if (!(Test-Path $compiler)) {
    choco install innosetup --yes --no-progress
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the installer compiler.' }
}
& $compiler scripts/windows-installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$commit = (git rev-parse HEAD).Trim()
@"
Source: https://github.com/zainepils/now-cleaner/tree/$commit
Commit: $commit
Built UTC: $([DateTime]::UtcNow.ToString('o'))
Platform: Windows x64
Signing: UNSIGNED personal-use preview. No publisher verification certificate.
Google Drive: unavailable in this Windows preview.
"@ | Set-Content -Encoding utf8 "$output/BUILD_INFO.txt"
python -m pip list --format=freeze | Set-Content -Encoding utf8 "$output/DEPENDENCIES.txt"
Copy-Item docs/windows.md "$output/INSTALL.txt"
$setup = Join-Path $output 'NOW-Cleaner-Windows-Setup.exe'
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  NOW-Cleaner-Windows-Setup.exe" | Set-Content -Encoding ascii "$output/SHA256SUMS.txt"
# Exercise installation without admin rights, then the installed executable.
$install = Join-Path $env:RUNNER_TEMP 'NOW Cleaner installed test'
$process = Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$install`"") -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installation failed: $($process.ExitCode)" }
python scripts/windows_smoke.py "$install/NOW Cleaner.exe"
if ($LASTEXITCODE -ne 0) { throw 'Installed app smoke test failed.' }
Write-Output 'Unsigned installer built, installed and tested using fictional content.'
