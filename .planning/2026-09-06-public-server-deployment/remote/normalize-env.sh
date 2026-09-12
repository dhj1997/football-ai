#!/bin/sh
set -eu

env_file=/opt/football-ai/app/.env
admin_key=$(sed -n 's/^ADMIN_API_KEY=//p' "$env_file" | tail -n 1)
if [ -z "$admin_key" ]; then
    echo "No rotated ADMIN_API_KEY found" >&2
    exit 1
fi

umask 077
tmp_file=$(mktemp /opt/football-ai/app/.env.XXXXXX)
trap 'rm -f -- "$tmp_file"' EXIT HUP INT TERM

sed \
    -e '/^ADMIN_API_KEY=/d' \
    -e 's/@47\.99\.207\.112:3306/@127.0.0.1:3306/' \
    "$env_file" > "$tmp_file"
printf '\nADMIN_API_KEY=%s\n' "$admin_key" >> "$tmp_file"
chown football-ai:football-ai "$tmp_file"
chmod 0600 "$tmp_file"
mv -f -- "$tmp_file" "$env_file"
trap - EXIT HUP INT TERM
