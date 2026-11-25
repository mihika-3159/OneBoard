#!/bin/sh
set -eu
# Use an explicitly generated lock file containing digest-qualified refs.
# Never source an arbitrary file as shell code.
lock=$1
tag=$2
node=$(sed -n 's/^NODE_IMAGE=//p' "$lock")
python=$(sed -n 's/^PYTHON_IMAGE=//p' "$lock")
printf '%s\n' "$node" | grep -Eq '^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$'
printf '%s\n' "$python" | grep -Eq '^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$'
docker build --file deploy/Dockerfile --build-arg "NODE_IMAGE=$node" --build-arg "PYTHON_IMAGE=$python" --tag "$tag" .
