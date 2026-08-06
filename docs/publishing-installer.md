# Publishing `mtrnix.com/install.sh`

The public installer is the small, version-controlled bootstrap at
`scripts/install-bootstrap.sh`. Do not publish the repository-root `install.sh`: that is
the full installer and requires the rest of the repository beside it.

## First deployment

Choose a document root on the web server; `/var/www/mtrnix.com` is used below. Copy to a
temporary name and rename it atomically so clients can never download a partial script:

```bash
scp scripts/install-bootstrap.sh deploy@mtrnix.com:/var/www/mtrnix.com/install.sh.new
ssh deploy@mtrnix.com \
  'chmod 0644 /var/www/mtrnix.com/install.sh.new && mv /var/www/mtrnix.com/install.sh.new /var/www/mtrnix.com/install.sh'
```

If Caddy serves the domain directly, a minimal site is:

```caddyfile
mtrnix.com {
    root * /var/www/mtrnix.com

    @installer path /install.sh
    header @installer Content-Type "text/plain; charset=utf-8"
    header @installer Cache-Control "no-cache"

    file_server
}
```

For nginx, add these headers to the `/install.sh` location:

```nginx
location = /install.sh {
    default_type text/plain;
    add_header Cache-Control "no-cache" always;
    try_files /install.sh =404;
}
```

Verify the deployed bytes, headers, syntax, and TLS endpoint:

```bash
curl -fsSI https://mtrnix.com/install.sh
curl -fsSL https://mtrnix.com/install.sh -o /tmp/metronix-install.sh
bash -n /tmp/metronix-install.sh
cmp scripts/install-bootstrap.sh /tmp/metronix-install.sh
```

## Keeping it current

The bootstrap normally changes less often than the application. New application versions
are discovered from Git tags, so publishing a new release does not require editing or
redeploying the bootstrap:

1. Run `make test-installer` in CI.
2. Create and push a new version tag.
3. The existing public bootstrap resolves that tag as `--version latest`.

Redeploy `scripts/install-bootstrap.sh` only when bootstrap behavior itself changes. Put
the atomic `scp`/`ssh` commands above in the release pipeline, with the host, user, and SSH
key stored as protected CI secrets. Never edit the server copy by hand.

Before relying on a new release, test both paths against a disposable machine:

```bash
curl -fsSL https://mtrnix.com/install.sh | bash -s -- --version VERSION -- -y
curl -fsSL https://mtrnix.com/install.sh | bash -s -- --update -- -y
```

Tags should be treated as immutable. If a release must be rolled back, point users to the
last known-good tag with `--version TAG`; do not move or overwrite an existing tag.
