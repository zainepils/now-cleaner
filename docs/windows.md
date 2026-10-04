# Windows Preview

This is a **local-only, unsigned preview** for Windows 10/11 on x64 Intel/AMD PCs.
It is not yet confirmed on a student's everyday PC. ARM Windows is not supported by
this installer. No Python installation or administrator account is required.

## Install and Try It

Download `NOW-Cleaner-Windows-Setup.exe` from the Windows preview release, run it,
then open **NOW Cleaner** from the Start menu. It installs for your Windows account.

The installer is unsigned. Windows may show an unknown-publisher or SmartScreen warning.
Only proceed if you trust this repository and download; use the per-app option if Windows
offers one. Do not turn off antivirus or override a malware detection. School/work device
policies may prevent running it. There is no automatic updater.

Start with fictional files before importing private course content. Create a module,
choose a ZIP or a folder containing ZIPs, review changes and save the update. Use
**Open course files** and **Open files to upload** to find the committed version.
Windows does not need symlinks, Developer Mode or administrator privileges for these actions.
The folders live inside saved revision directories rather than top-level Mac folder links.

Choose a destination on the same drive as your user profile for this preview; cross-drive
module destinations are not supported. Previous versions remain available through History.

Visual Word/PowerPoint packs need LibreOffice installed separately. The app detects its
standard Program Files installation. Text/PDF packs do not need LibreOffice.

**Google Drive connection is unavailable on Windows in this preview.** There is no
plaintext credential fallback. Use the local files and NotebookLM replacement checklist.
The one-off cleaner's optional OpenAI filename naming still depends on a configured key;
leave it unconfigured for local-only operation.

## Data and Removal

Inventory and previews are under `%LOCALAPPDATA%\NOW Cleaner`. Course files stay in
the destination you selected. Windows uses your account's existing folder permissions;
the app does not configure custom access controls or encrypt local files.

Uninstall through Windows Settings > Apps. Saved modules, history, course folders and
one-off naming caches remain until you remove them separately. See [privacy guidance](privacy.md).

## PC Check Before Wider Sharing

1. Install, launch, close and reopen the app.
2. Import a fictional ZIP, then a folder of ZIPs.
3. Re-import unchanged files and check earlier weeks remain after a partial update.
4. Open current/latest files and history; check filenames and layout are readable.
5. Test an Office visual pack with LibreOffice installed, if you use that feature.
6. Share screenshots or error messages without real course content or personal paths.

GitHub Windows tests and packaged/installed workflow checks are automated evidence,
not a substitute for this hands-on check. Check the attached source commit and checksum;
neither proves safety. This remains a personal-use, AI-assisted student project.
