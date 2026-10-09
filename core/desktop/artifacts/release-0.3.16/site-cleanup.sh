set -eu
date -u +%Y-%m-%dT%H:%M:%SZ
grep -vF 'AAAAC3NzaC1lZDI1NTE5AAAAIGslucPESqt758J0JCxkqRrSrXTf+3wXkjjU6pmuKr+j' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp0316 || true
mv /root/.ssh/authorized_keys.tmp0316 /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
wc -l < /root/.ssh/authorized_keys
ls -1 /var/tmp/Sunday-site-mobile-0.3.16-*.upload.tar.gz 2>/dev/null || echo 'no site stages'
ls -1 /var/tmp/Sunday-desktop-0.3.16-*.upload.exe 2>/dev/null || echo 'no installer stages'
readlink -f /var/www/lamtools/site
date -u +%Y-%m-%dT%H:%M:%SZ
