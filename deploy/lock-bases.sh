#!/bin/sh
set -eu
# Generate once and retain the lock alongside release artifacts.
# Future builds use the same base references without resolving tags again.
output=$1
test ! -e "$output"
docker pull node:22-bookworm-slim >&2
docker pull python:3.11-slim-bookworm >&2
node=$(docker image inspect node:22-bookworm-slim --format '{{index .RepoDigests 0}}')
python=$(docker image inspect python:3.11-slim-bookworm --format '{{index .RepoDigests 0}}')
(umask 077; printf 'NODE_IMAGE=%s\nPYTHON_IMAGE=%s\n' "$node" "$python" > "$output")
