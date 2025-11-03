# GitHub Actions Release Setup

This repository includes automated build and release workflows that trigger when you push tags to the main branch.

## Quick Setup

1. **Choose a workflow:**
   - Use `release.yml` for basic functionality
   - Use `release-advanced.yml` for more robust handling of complex projects

2. **Enable the workflow:**
   The workflows are triggered automatically when you push a tag that matches the pattern `v*` (e.g., `v1.0.0`, `v2.1.3`).

3. **Create a release:**
   ```bash
   # Tag your current commit
   git tag v1.0.0
   
   # Push the tag to trigger the build
   git push origin v1.0.0
   ```

## What the workflow does:

1. **Builds your macOS app** using the Release configuration
2. **Creates a DMG file** with your app and an Applications folder link
3. **Generates release notes** from your git commits
4. **Creates a GitHub release** with the DMG attached
5. **Uploads build artifacts** for troubleshooting

## Optional: Code Signing

To enable code signing for your releases, add these secrets to your GitHub repository:

1. Go to your repository **Settings** → **Secrets and variables** → **Actions**
2. Add these repository secrets:
   - `CERTIFICATES_P12`: Your Developer ID certificate exported as base64
   - `CERTIFICATES_PASSWORD`: The password for your P12 certificate

### To export your certificate as base64:

```bash
# Export certificate from Keychain as .p12 file
# Then convert to base64:
base64 -i YourCertificate.p12 | pbcopy
```

## Advanced Configuration

### Custom DMG Styling
You can customize the DMG appearance by modifying the `hdiutil create` command in the workflow.

### Custom Build Settings
Modify the `xcodebuild` commands to use specific configurations, architectures, or build settings.

### Custom Release Notes
The workflow automatically generates release notes from git commits. You can customize this in the "Generate Release Notes" step.

## Troubleshooting

1. **Build fails:** Check the "List available schemes" step output to see available schemes
2. **No app found:** Ensure your Xcode project builds successfully locally
3. **DMG creation fails:** Check that the app was exported correctly

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