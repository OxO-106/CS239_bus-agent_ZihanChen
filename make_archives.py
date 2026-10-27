"""Build the two submission archives from the files git tracks (or would track).

    python make_archives.py <name> <uid>

writes <name>-bus-agent-<uid>-requirements.tar.gz (bus-agent/) and
<name>-bus-agent-<uid>-whole.tar.gz (src/, plus bus-agent/, README.md and LICENSE so its links resolve).
Ignored files (.env, data/local/, caches) are never included.
"""
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = "bus-agent"


def files(*tops):
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *tops],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if (ROOT / p).is_file()]


def build(name, paths):
    with tarfile.open(ROOT / name, "w:gz") as tar:
        for p in sorted(paths):
            tar.add(ROOT / p, arcname=p)
    print(f"{name}: {len(paths)} files")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    name, uid = sys.argv[1:]
    build(f"{name}-{APP}-{uid}-requirements.tar.gz", files(APP))
    build(f"{name}-{APP}-{uid}-whole.tar.gz", files("src", APP, "README.md", "LICENSE"))


if __name__ == "__main__":
    main()
