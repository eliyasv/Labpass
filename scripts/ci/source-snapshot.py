"""Copy Git-visible source for scanning; exclude ignored local credentials and tooling."""

import argparse
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    destination = args.destination.resolve()
    # Keep the snapshot outside its own input tree.
    if destination.is_relative_to(root):
        raise SystemExit("Place the scan snapshot outside the checkout")
    destination.mkdir(parents=True, exist_ok=False)
    # Include tracked and new source files while respecting Git's ignore rules.
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    for name in dict.fromkeys(filter(None, names)):
        source = root / name
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise SystemExit("Source snapshots do not follow symbolic links")
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


if __name__ == "__main__":
    main()
