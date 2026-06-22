from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_RUNTIME_FILES = {"data/.gitkeep", "exports/.gitkeep"}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".docx",
    ".jks",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "Bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE),
}
GENERIC_SECRET = re.compile(
    r"(?im)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b"
    r"\s*[:=]\s*[\"']([^\"']{12,})[\"']"
)
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
CN_ID = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "localhost"}
PLACEHOLDER_PREFIXES = ("env:", "keyring:", "your_", "example", "placeholder", "changeme")


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item for item in result.stdout.decode().split("\0") if item]


def forbidden_path(path: str) -> str | None:
    lowered = path.lower()
    name = Path(lowered).name
    if lowered in ALLOWED_RUNTIME_FILES or lowered == ".env.example":
        return None
    if lowered == ".env" or "/.env" in lowered or name.startswith(".env."):
        return "environment file"
    if lowered.startswith(("data/", "exports/")):
        return "runtime data or export"
    if Path(lowered).suffix in FORBIDDEN_SUFFIXES or name.startswith("id_rsa"):
        return "secret, database, or generated document"
    if name.startswith(("credentials", "secrets")) and Path(name).suffix in {
        ".json",
        ".toml",
        ".yaml",
        ".yml",
    }:
        return "credential configuration"
    return None


def scan_text(path: str, text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(label)
    for match in GENERIC_SECRET.finditer(text):
        value = match.group(1).lower()
        if not value.startswith(PLACEHOLDER_PREFIXES) and value not in {"null", "none"}:
            findings.append("non-placeholder secret assignment")
            break
    if PHONE.search(text):
        findings.append("possible mainland China phone number")
    if CN_ID.search(text):
        findings.append("possible mainland China ID number")
    for address in EMAIL.findall(text):
        domain = address.rsplit("@", 1)[1].lower()
        if domain not in SAFE_EMAIL_DOMAINS and not domain.endswith(".example"):
            findings.append("possible personal email address")
            break
    return findings


def main() -> int:
    findings: list[str] = []
    files = tracked_files()
    for relative in files:
        reason = forbidden_path(relative)
        if reason:
            findings.append(f"{relative}: forbidden tracked path ({reason})")
            continue
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(f"{relative}: {item}" for item in scan_text(relative, text))
    if findings:
        print("Privacy check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"Privacy check passed for {len(files)} publishable files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
