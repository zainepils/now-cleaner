# Personal Google Drive Setup

Drive syncing is optional. Local modules work without a Google account.

## Configure a desktop client

1. Open [Google Cloud Console](https://console.cloud.google.com/) and choose or create a project.
2. Enable **Google Drive API** and **Google Docs API** in that project.
3. Configure Google Auth Platform branding/audience for personal testing. Add your personal Google account as a test user if the app is in Testing status.
4. Create an OAuth client of type **Desktop app**, then download its JSON. Keep it outside this repository.
5. In NOW Cleaner, open **More > Google Drive connection**, click **Connect Google Drive**, and select that JSON. Complete consent in your browser.

The app requests only `drive.file`, allowing access to files it creates or which are explicitly made available to it. Sign-in uses PKCE and a temporary localhost callback that closes after consent. Access and refresh tokens are stored only in macOS Keychain. No password is requested by NOW Cleaner. There is no hosted app UI.

A previously downloaded desktop client may work if its Google Cloud project remains available to you and both APIs are enabled. A web-client JSON cannot be used. Testing-mode OAuth applications can require reconnection as tokens expire; personal setup is not a public OAuth distribution setup.

## Required NotebookLM sync test

No real course packs are uploaded until you record a successful test for their format and Google account.

1. Click **Create Test Sources**. This creates a private synthetic Google Doc and PDF containing VERSION ONE. It sends no course material.
2. Open NotebookLM with the same personal account, create a test notebook, and import both sources **from Google Drive**, not by downloading/uploading local copies.
3. Click **Update Test Sources** in NOW Cleaner. The existing Drive IDs must be retained.
4. Open that notebook and inspect both existing sources. Use its sync control if available. Confirm they contain **VERSION TWO - SYNC CONFIRMED** without adding another source or deleting the old source.
5. Check only the formats that actually worked, then click **Save Verification**.

Verification is your manual observation, not automated proof. A format that fails remains gated. Modules containing separate audio/media sources currently use local export because those formats do not have this app's sync verification path.

Google's [source guidance](https://support.google.com/gemininotebook/answer/16215270?hl=en) describes Drive source sync. The app never claims a completed NotebookLM sync just because a Drive request succeeded.

## Daily use

Create a module in Drive mode, set its notebook link, and import exports. Preview changes, resolve conflicts or uncertain renames if needed, prepare files, and save the local update. Categories are automatic and can be changed optionally. Click **Send to Google Drive**. Add new packs from Drive to NotebookLM once. Later updates modify those same files.

Do not edit managed packs in Drive. External modifications, missing files or account mismatches block overwriting; restore the expected file or use local export while investigating. A failed upload does not invalidate successful receipts or remove local data. Retry operates on outstanding packs.

Retired packs are listed in the update checklist. Remove their sources manually from NotebookLM; the app does not delete them or their Drive files automatically. They continue to consume the estimated source budget until you confirm their removal using **Retired Sources** in the app. Keep room for them and other sources.

## Privacy and limitations

- Connecting does not upload course material; syncing a Drive-mode module does. Only do this when permitted by the content owner's and NTU's policies.
- No public sharing permission is created. This cannot override account or university sharing policies.
- Local originals, inventory, history and reports can contain private filenames/content. Do not publish them.
- Disconnect removes saved tokens, not files already uploaded to Drive. Reconnect to the same account to retain existing links.
- Public release OAuth verification, app notarization, direct NotebookLM APIs, scraping, scheduling and NTU login are not included.

Official references: [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [file uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads).
