# GitHub Actions Release Setup

This repository includes automated build and release workflows that trigger when you push tags to the main branch.

## Quick Setup

1. **Choose a workflow:**
   - Use `release.yml` for **unsigned builds** (fastest, simplest option)
   - Use `release-signed.yml` for **signed and notarized builds** (for distribution outside the App Store)

2. **Enable the workflow:**
   The workflows are triggered automatically when you push a tag that matches the pattern `v*` (e.g., `v1.0.0`, `v2.1.3`).

3. **Create a release:**
   ```bash
   # Tag your current commit
   git tag v1.0.0

   # Push the tag to trigger the build
   git push origin v1.0.0
   ```

   Or use the workflow dispatch feature to trigger manually from GitHub Actions tab.

## What the workflow does:

1. **Builds your macOS app** using the Release configuration
2. **Creates a DMG file** with your app and an Applications folder link
3. **Generates release notes** from your git commits
4. **Creates a GitHub release** with the DMG attached
5. **Uploads build artifacts** for troubleshooting

## Code Signing (Optional - Only for `release-signed.yml`)

The `release-signed.yml` workflow automatically detects if signing certificates are available and builds accordingly:
- **With certificates:** Builds a signed app
- **Without certificates:** Falls back to unsigned build

### To enable code signing:

1. Go to your repository **Settings** → **Secrets and variables** → **Actions**
2. Add these **required** secrets:
   - `CERTIFICATES_P12`: Your Developer ID Application certificate exported as base64
   - `CERTIFICATES_PASSWORD`: The password for your P12 certificate

3. Add these **optional** secrets for notarization:
   - `NOTARIZATION_USERNAME`: Your Apple ID email
   - `NOTARIZATION_PASSWORD`: App-specific password (generate at appleid.apple.com)
   - `NOTARIZATION_TEAM_ID`: Your 10-character Team ID

### To export your certificate as base64:

```bash
# 1. Export certificate from Keychain as .p12 file
#    (Keychain Access → Right-click certificate → Export)
# 2. Convert to base64:
base64 -i YourCertificate.p12 | pbcopy
# 3. Paste into GitHub Secrets
```

## Advanced Configuration

### Custom DMG Styling
You can customize the DMG appearance by modifying the `hdiutil create` command in the workflow.

### Custom Build Settings
Modify the `xcodebuild` commands to use specific configurations, architectures, or build settings.

### Custom Release Notes
The workflow automatically generates release notes from git commits. You can customize this in the "Generate Release Notes" step.

## Which Workflow Should I Use?

### Use `release.yml` if:
- You want quick, simple releases
- You're distributing to a small group of users who can bypass Gatekeeper
- You're testing the build process

### Use `release-signed.yml` if:
- You're distributing to external users
- You want to avoid "unverified developer" warnings
- You have an Apple Developer account
- You want the most professional distribution

## Troubleshooting

1. **Build fails:** Check the "List available schemes" step output to see available schemes
2. **No app found:** Ensure your Xcode project builds successfully locally with `xcodebuild -scheme Flycut -configuration Release`
3. **DMG creation fails:** Check that the app was exported correctly in the previous step
4. **Code signing fails:** Verify your certificate is valid and the P12 password is correct
5. **Notarization fails:** Ensure you're using an app-specific password, not your Apple ID password

## File Structure After Build

```
build/
├── YourApp.xcarchive          # Xcode archive
├── YourApp-1.0.0.dmg         # Final DMG for distribution
├── Export/                    # Exported app bundle
│   └── YourApp.app
├── dmg-staging/              # DMG creation staging area
└── ExportOptions.plist       # Export configuration
```

The DMG will be automatically attached to your GitHub release and available for download.