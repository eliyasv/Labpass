"""Install checksum-pinned official scanner binaries, without extracting archive paths."""

import argparse
import hashlib
import io
import json
import platform
import re
import tarfile
import urllib.request
from pathlib import Path


def binary_from_archive(data, name, expected_hash):
    # Verify downloaded bytes against the reviewed pin before parsing the archive.
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError("security tool checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        # Read only the named regular file; never extract archive-controlled paths.
        member = archive.getmember(name)
        if not member.isfile():
            raise ValueError("security tool must be a regular file")
        return archive.extractfile(member).read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise SystemExit("Security tool pins target Linux x86_64")
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "security/tools.json").read_text())
    args.destination.mkdir(parents=True, exist_ok=True)
    for name, settings in manifest.items():
        if not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/[^?#]+",
            settings["url"],
        ):
            raise ValueError(
                "Security tools must come from official HTTPS release URLs"
            )
        request = urllib.request.Request(
            settings["url"], headers={"User-Agent": "LabPass-CI"}
        )
        # The manifest URL is restricted to HTTPS GitHub releases and its content is hashed.
        with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310
            binary = binary_from_archive(response.read(), name, settings["sha256"])
        target = args.destination / name
        if target.is_symlink():
            raise SystemExit("Refusing to replace a symbolic link")
        target.write_bytes(binary)
        target.chmod(0o755)
        print(f"Installed {name} {settings['version']}")


if __name__ == "__main__":
    main()
