# Metatron Installer Distribution Guide

## Overview

The Metatron Core installer (`install.sh`) is distributed securely to users through multiple channels, all served over HTTPS. This guide explains the distribution options, how users access the installer, and how to maintain the installation process.

## Distribution Channels

### GitHub Releases (Recommended)

The recommended approach for most users is to download from GitHub Releases, which provides clear versioning and automatic verification.

**Download URL Pattern:**
```
https://github.com/openclaw/metatron/releases/download/v{VERSION}/install.sh
https://github.com/openclaw/metatron/releases/download/v{VERSION}/install.sha256
```

**Example (Latest Release):**
```bash
# Download and verify the installer
curl -L https://github.com/openclaw/metatron/releases/download/v1.0.0/install.sh -o install.sh
curl -L https://github.com/openclaw/metatron/releases/download/v1.0.0/install.sha256 -o install.sha256

# Verify checksum matches
sha256sum -c install.sha256

# Run installer
bash install.sh
```

**Advantages:**
- Clear version tracking (release tags match installer versions)
- Automatic asset management via GitHub Actions workflow
- Release notes document changes and features
- GitHub's infrastructure provides global CDN coverage

**Release Process:**
When a new release is created in GitHub:
1. GitHub Actions workflow automatically triggers (`.github/workflows/release-installer.yml`)
2. Workflow validates installer syntax with `bash -n install.sh`
3. Workflow generates fresh checksum: `sha256sum install.sh > install.sha256`
4. Workflow uploads both `install.sh` and `install.sha256` as release assets
5. Assets become publicly available within seconds

### Raw GitHub (Alternative)

For users who prefer always getting the latest version (without versioning):

**Download URL:**
```
https://raw.githubusercontent.com/openclaw/metatron/main/install.sh
https://raw.githubusercontent.com/openclaw/metatron/main/.sha256sum
```

**Example:**
```bash
# Download latest from main branch
curl -L https://raw.githubusercontent.com/openclaw/metatron/main/install.sh | bash

# Or with checksum verification (recommended)
curl -L https://raw.githubusercontent.com/openclaw/metatron/main/install.sh -o install.sh
curl -L https://raw.githubusercontent.com/openclaw/metatron/main/.sha256sum -o .sha256sum
sha256sum -c .sha256sum
bash install.sh
```

**Advantages:**
- Always latest version
- No version management needed
- Simple one-liner

**Disadvantages:**
- No version guarantees (API may change between runs)
- Breakage potential if main branch is in unstable state
- Not recommended for production deployments

### Custom CDN / Static Site

For organizations or users running Metatron at scale, you can host the installer on your own infrastructure.

**Setup with Nginx:**
```nginx
server {
    listen 443 ssl http2;
    server_name app.mtrnix.com;

    ssl_certificate /etc/ssl/certs/app.mtrnix.com.crt;
    ssl_certificate_key /etc/ssl/private/app.mtrnix.com.key;

    location /install.sh {
        alias /var/www/metatron/install.sh;
        add_header Content-Type text/plain;
        add_header Cache-Control "public, max-age=3600";
    }

    location /install.sha256 {
        alias /var/www/metatron/install.sha256;
        add_header Content-Type text/plain;
        add_header Cache-Control "public, max-age=3600";
    }
}
```

**Setup with Cloudflare Pages:**
1. Fork/clone Metatron repository
2. Create `/public/install.sh` and `/public/install.sha256`
3. Deploy via Cloudflare Pages
4. Access at: `https://{project}.pages.dev/install.sh`

**Example Download:**
```bash
curl https://app.mtrnix.com/install.sh | bash
```

**Maintenance:**
When updating to a new version:
1. Replace `install.sh` on your server
2. Update `.sha256sum` checksum file
3. Keep both files in sync (checksum must match latest installer)

## Security Considerations

### HTTPS is Mandatory

All distribution channels enforce HTTPS encryption:
- **GitHub Releases:** Automatically HTTPS via github.com
- **Raw GitHub:** Automatically HTTPS via githubusercontent.com
- **Custom CDN:** Configure SSL/TLS with valid certificate

Never serve the installer over plain HTTP. Users piping scripts to bash face full code execution, so transport security is critical.

### Checksum Verification

Before running the installer, users should verify the checksum to ensure:
- No network man-in-the-middle attacks occurred
- File wasn't corrupted during transfer
- You're running the exact version you intended

**Verification Process:**

```bash
# Download installer and checksum
curl -L https://github.com/openclaw/metatron/releases/download/v1.0.0/install.sh -o install.sh
curl -L https://github.com/openclaw/metatron/releases/download/v1.0.0/install.sha256 -o install.sha256

# Verify checksum (should print "install.sh: OK")
sha256sum -c install.sha256

# Only then run the installer
bash install.sh
```

See `docs/INSTALL.md` for complete verification instructions.

### Secure Code Practices

The installer (`install.sh`) follows security best practices:
- **No `eval` command:** All code is explicit, no dynamic execution
- **Proper quoting:** Variables quoted as `"$VAR"` to prevent word splitting
- **Explicit error handling:** `set -euo pipefail` prevents silent failures
- **Shellcheck compliant:** Code verified by shellcheck for security issues

## Maintenance and Updates

### Creating a New Release

1. **Update version in docs and code** as needed
2. **Test locally:**
   ```bash
   make test-installer      # Verify syntax
   make verify-checksum     # Verify checksum is current
   make prepare-release     # Full pre-release check
   ```
3. **Create GitHub Release:**
   - Go to: https://github.com/openclaw/metatron/releases/new
   - Tag version: `v1.0.0` (matches package version)
   - Title: "Release v1.0.0: Feature description"
   - Description: Release notes (features, fixes, breaking changes)
   - Click "Publish release"
4. **Workflow automation takes over:**
   - GitHub Actions automatically uploads `install.sh` and `install.sha256`
   - Assets available within seconds
   - Users can download and verify

### Updating the Installer

When you modify `install.sh`:
1. **Make your changes** to the file
2. **Validate:** `make test-installer` (syntax check passes)
3. **Update checksum:** `make update-checksum`
4. **Commit:** `git add install.sh .sha256sum && git commit -m "infra: update installer ..."`
5. **Push to main:** `git push origin main`
6. **Create release:** Create GitHub release for new version

The checksum file `.sha256sum` in the repository is used for:
- `make verify-checksum` target (local verification)
- Reference in documentation

The GitHub Actions workflow generates a fresh checksum when creating releases, ensuring release checksums match exactly.

### Monitoring and Troubleshooting

#### 404 Errors When Downloading

**From GitHub Releases:**
- Verify release exists: Check https://github.com/openclaw/metatron/releases
- Verify version tag matches URL (e.g., `v1.0.0` tag for `v1.0.0` URL)
- Wait 10-30 seconds after release creation (CDN propagation)

**From Custom CDN:**
- Verify file exists on server: `ls -la /var/www/metatron/install.sh`
- Check web server logs: `tail -f /var/log/nginx/access.log`
- Verify SSL/TLS certificate is valid

#### Checksum Mismatch

If `sha256sum -c install.sha256` fails:

1. **Checksum file is outdated:**
   ```bash
   # Update checksum if installer changed
   make update-checksum
   git add .sha256sum && git commit -m "infra: update checksum"
   ```

2. **File was corrupted during transfer:**
   ```bash
   # Re-download and try again
   rm install.sh install.sha256
   # Download from GitHub releases or custom CDN again
   ```

3. **Wrong version of installer:**
   - Verify you're using the correct release version
   - Check GitHub releases page for latest version

#### Installer Fails During Execution

See `docs/INSTALL.md` for troubleshooting guide covering:
- Python 3.12+ not found
- Docker/Docker Compose not installed
- Permission denied errors
- Network connectivity issues

## Next Steps

- **For users:** See `docs/INSTALL.md` for installation instructions
- **For operators:** See `docs/DEPLOYMENT.md` for production setup
- **For contributors:** See `CONTRIBUTING.md` for development workflow

---

**Related Files:**
- `install.sh` — Installer script
- `.sha256sum` — Checksum verification file
- `docs/INSTALL.md` — User installation guide
- `.github/workflows/release-installer.yml` — Automated release workflow
