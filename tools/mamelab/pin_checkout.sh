#!/bin/sh
# pin_checkout.sh [REV] [DEST_ROOT] - export REV (default HEAD) of this repo with `git archive`
# into DEST_ROOT/<rev>/robotron_ai and print that path, ready for run_ab.py --checkout.
# DEST_ROOT defaults to $MAMELAB_CK or ~/Code/robotron_data/mamelab/ck. The directory must be
# named robotron_ai (it is the package), hence the archive prefix.
set -e
rev=${1:-HEAD}
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
dest=${2:-${MAMELAB_CK:-$HOME/Code/robotron_data/mamelab/ck}}
sha=$(git -C "$repo" rev-parse --short "$rev")
tag=$(printf '%s' "$rev" | tr '/ ' '__')-$sha
mkdir -p "$dest/$tag"
git -C "$repo" archive --prefix=robotron_ai/ "$rev" | tar -x -C "$dest/$tag"
echo "$dest/$tag/robotron_ai"
