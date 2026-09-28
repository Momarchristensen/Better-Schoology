import re
import subprocess
import sys


VERSION_PATTERN = re.compile(r"^v\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?$")


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        capture_output=True,
    )


def main() -> int:
    version = input("Enter the release version (for example, 1.2.3): ").strip()
    if not version:
        print("A release version is required.", file=sys.stderr)
        return 1

    tag = f"v{version[1:]}" if version[:1].lower() == "v" else f"v{version}"
    if not VERSION_PATTERN.fullmatch(tag):
        print(
            "Invalid version. Use a version such as 1.2.3 or v1.2.3.",
            file=sys.stderr,
        )
        return 1

    try:
        run_git("rev-parse", "--is-inside-work-tree")
        run_git("rev-parse", "--verify", f"refs/tags/{tag}")
    except subprocess.CalledProcessError:
        pass
    else:
        print(f"Tag {tag} already exists locally.", file=sys.stderr)
        return 1

    try:
        run_git("tag", "-a", tag, "-m", f"Release {tag}")
        run_git("push", "origin", tag)
    except FileNotFoundError:
        print("Git was not found. Install Git and try again.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout.strip())
        if error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        print(f"Release {tag} was not pushed.", file=sys.stderr)
        return 1

    print(f"Release {tag} pushed. GitHub Actions will run build-release.yml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())