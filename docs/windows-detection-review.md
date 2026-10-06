# Windows Installer Detection Review

Status as of 6 October 2026: **unresolved; do not install the v0.3.1 Windows release**.
A false positive has not been confirmed. Do not disable antivirus, add exclusions,
or bypass Defender to run it.

## Exact File

- File: `NOW-Cleaner-Windows-Setup.exe`, v0.3.1, 29,892,014 bytes.
- SHA-256: `40b6676ce3915117579e7e2bb4ed7b6cbe89e90b36d374b5f46ada4173530d06`.
- [VirusTotal report](https://www.virustotal.com/gui/file/40b6676ce3915117579e7e2bb4ed7b6cbe89e90b36d374b5f46ada4173530d06/detection):
  1/69 engines, Microsoft `Trojan:Win32/Wacatac.B!ml`, observed 6 October 2026.
  The report's analysis timestamp was 5 October 2026 at 22:32:16 British Summer Time.

## Checks Completed

1. Independently downloaded the original
   [GitHub Actions artifact](https://github.com/zainepils/now-cleaner/actions/runs/37238164703/artifacts/11315748832).
   Its installer has the same SHA-256 as the released installer and VirusTotal
   report. No difference between that build artifact and the release was found.
2. Reviewed the build evidence and packaging files at source commit
   [`fb40ce5197a8f20d178e59ff7b88f4ab011591a1`](https://github.com/zainepils/now-cleaner/tree/fb40ce5197a8f20d178e59ff7b88f4ab011591a1).
   The Windows build used Python 3.12.10, PyInstaller 6.22.3 and Inno Setup 6.7.1.
   It packages a directory-based Python application, not a PyInstaller one-file
   executable. The Inno installer is compressed and unsigned.
3. Reviewed installer actions: per-user installation, Start menu shortcut,
   uninstall registration, and an optional, unchecked post-install app launch.
   No custom installer script, Defender exclusion, scheduled task, service or
   startup registration is present in the installer definition.
4. Inspected network/process-related application source paths. These include
   opening folders/browser links, launching the bundled one-off backend, and
   user-requested LibreOffice conversion. Optional one-off AI naming contacts
   OpenAI when a key is configured; module processing is local. Drive is disabled
   in the Windows preview. This was a targeted inspection, not a complete audit
   of all application/dependency code or proof of the binary's contents.
5. Read the VirusTotal Behavior and Relations views. The visible activity includes
   an Inno temporary setup process, installed runtime files and uninstall registry
   entries. The report also contains automated MITRE behavior signatures, including
   process injection and impact labels. These are not dismissed as harmless, but
   labels alone do not establish malicious intent or identify the triggering code.
   The displayed network communication was UDP to `162.159.36.2:53`; memory-pattern
   URLs are not proof those websites were contacted.

## Limits and Pending Work

- The installer was not executed during this investigation. No fresh Windows
  Defender scan or isolated Windows runtime analysis has been performed here.
- Innoextract 1.9 could not parse this Inno Setup 6.7.1 installer. It reported a
  loader/version/checksum error; this is not evidence of corruption or malware,
  and package contents have not been independently extracted and verified.
- Passing functional CI tests is not antivirus clearance.
- Dependency ranges and the build-tool installation are not fully pinned or
  hash-locked. Matching the original artifact does not rule out a dependency or
  build-environment issue. A rebuild would not be assumed byte-reproducible.
- The specification enables UPX if available. Actual UPX use in this build has
  not been established; compression is not assumed to explain the detection.
- The exact installer was submitted through the
  [Microsoft submission portal](https://www.microsoft.com/en-us/wdsi/filesubmission)
  on 6 October 2026. The portal confirmed **Submitted**, with final determination
  **Pending**. Its current detection showed `Program:Win32/Wacapew.C!ml`, distinct
  from the earlier VirusTotal label, with definition version `1.459.574.0`.
  This is not analyst clearance or confirmation of a false positive. The
  account-specific submission reference is retained privately, not published.
- Await Microsoft's determination before removing the warning. If additional analysis is
  requested, inspect/scan the installed app payload in an isolated Windows
  environment, retaining Defender protections.
- Do not change packaging merely to evade detection. Any future release needs
  its own scan and verification; clearance for one hash does not cover another.

## Suggested Microsoft Submission Description

```text
Please review the detection of NOW-Cleaner-Windows-Setup.exe v0.3.1.
VirusTotal reports Microsoft Trojan:Win32/Wacatac.B!ml (1/69 engines).
SHA-256: 40b6676ce3915117579e7e2bb4ed7b6cbe89e90b36d374b5f46ada4173530d06
Public source: https://github.com/zainepils/now-cleaner/tree/fb40ce5197a8f20d178e59ff7b88f4ab011591a1
Build: https://github.com/zainepils/now-cleaner/actions/runs/37238164703
The released installer matches the original CI artifact's SHA-256.
This is an unsigned Inno Setup 6.7.1 installer for a Python/Tkinter desktop app,
packaged using PyInstaller 6.22.3 in directory mode. It organises user-selected
course ZIP exports locally and generates document packs for manual upload.
It installs per user without admin rights and has no configured startup task
or service. Optional one-off OpenAI filename naming requires a configured key;
Google Drive integration is unavailable in this Windows preview.
A false positive is suspected but not established. Please determine whether
this file is malicious or incorrectly detected and advise on the result.
```
