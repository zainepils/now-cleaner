# Security Policy

## Reporting Concerns

Use [GitHub's private vulnerability reporting form](https://github.com/zainepils/now-cleaner/security/advisories/new)
to report a vulnerability; private reporting is enabled. Do not publish credentials, real course
exports, personal data or exploit details in a public issue. If the private route is
unavailable, open a minimal issue requesting a private contact channel, without sensitive
details. No response-time guarantee or bug bounty is offered.

The current main branch is maintained on a best-effort basis. Older app builds may
not receive fixes; there is no formal long-term-support release policy.

## System and Boundaries

NOW Cleaner is a personal-use macOS desktop app and CLI. ZIP contents, filenames,
nested documents and externally modified output/Drive files are untrusted inputs.
Assets include local course content, inventory/history, Google credentials and an
optional user-configured OpenAI key. See [privacy and data flow](docs/privacy.md).

Intended properties include bounded archive/document processing, rejection of unsafe
paths and symlinks, no replacement of unrelated output folders, preservation of previous
versions on failure, explicit review for removals, and no silent overwriting of externally
modified Drive sources. Drive tokens must remain in Keychain with no plaintext fallback.
Course content must not be sent to the maintainer or used for OpenAI filename naming.

These are properties to review, not claims that tests prove immunity to vulnerabilities.
No vulnerability category is excluded solely because the app is local or AI-assisted.

## Known Limits

Process trusted course exports only. Archive budgets are not malware detection or a
complete sandbox for LibreOffice, PDF and image parsers. Local course/history files
are not app-encrypted. The optional legacy OpenAI key file is plaintext. Dependencies,
browsers and Google/OpenAI services have their own security boundaries. Public OAuth
distribution and Apple notarization are not implemented in this personal-use release.

Tests use synthetic content; live NotebookLM sync requires manual verification.
Security checks, signing and test passes are not security certification.
