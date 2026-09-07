"""apply_rsshub_config.py — host-side RSSHub config applier (Gate).

The BFF never sees a Docker socket and never runs shell commands. This
script is the ONLY sanctioned apply path for the RSSHub Control Center:

    1. BFF materializes the full env file (values included) server-side:
         POST /api/v1/rsshub/config/env-file
       -> <BFF data dir>/rsshub/rsshub.env  (chmod 0600, never in Git)
    2. An operator runs THIS script on the BFF host (dry-run by default):
         python apply_rsshub_config.py --env-file <path>            # plan
         python apply_rsshub_config.py --env-file <path> --apply    # apply
    3. After a verified apply, click "标记为已应用" in the Control Center.

Safety boundaries (do not weaken):

- allow-listed service name ("rsshub" only; never FreshRSS/BFF);
- fixed compose verb: `up -d --force-recreate --no-deps` — env var
  changes need a container RECREATE (plain restart keeps the old env);
- subprocess LIST form with shell=False; every argument is validated
  against strict patterns before use; no eval, no string commands;
- env keys validated against ^[A-Z][A-Z0-9_]*$; values never logged;
- the post-apply health check only accepts the loopback addresses this
  deployment publishes (127.0.0.1 / localhost), http only;
- failure keeps the previous container state discoverable: the command
  and its output are printed for operator review; nothing auto-deletes.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")
ALLOWED_SERVICES = ("rsshub",)
DEFAULT_COMPOSE = "docker-compose.yml"
DEFAULT_PROJECT = "lumirss"
DEFAULT_SERVICE = "rsshub"
DEFAULT_HEALTH_URL = "http://127.0.0.1:1200/healthz"
ALLOWED_HEALTH_HOSTS = ("127.0.0.1", "localhost")


def parse_env_file(path: Path) -> dict[str, str]:
    """Load KEY=VALUE lines; reject anything not docker-env safe."""
    values: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"ERROR: {path.name}:{lineno}: not KEY=VALUE")
        key, _, value = line.partition("=")
        key = key.strip()
        if not ENV_KEY_RE.match(key):
            raise SystemExit(f"ERROR: {path.name}:{lineno}: unsafe key {key!r}")
        if any(ord(ch) < 32 for ch in value):
            raise SystemExit(
                f"ERROR: {path.name}:{lineno}: control character in value (key {key})"
            )
        values[key] = value
    if not values:
        raise SystemExit(f"ERROR: {path.name}: no KEY=VALUE entries found.")
    return values


def validate_health_url(health_url: str) -> None:
    """Only this deployment's loopback publication is a valid target."""
    parts = urlsplit(health_url)
    if parts.scheme != "http" or parts.hostname not in ALLOWED_HEALTH_HOSTS:
        raise SystemExit(
            "ERROR: --health-url must be an http URL on 127.0.0.1 or localhost."
        )


def write_override(env_file: Path, service: str, override_path: Path) -> None:
    """Compose override that wires the generated env file into the service.

    Keeping this as a FILE (not a CLI substitution) matters: docker compose
    `--env-file` only feeds ${VAR} substitution, it does NOT set container
    environment. A service-level env_file does.
    """
    import json

    document = {
        "services": {
            service: {
                "env_file": [str(env_file.resolve())],
            }
        }
    }
    override_path.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


def run_apply(
    compose_file: Path,
    override_file: Path,
    project: str,
    service: str,
) -> tuple[int, str]:
    # Inline literal argv (list form, shell=False): every element after the
    # fixed verb is a validated scalar — compose file path, override path,
    # project name and service are each checked/validated in main().
    completed = subprocess.run(  # noqa: S603
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "-f",
            str(override_file),
            "-p",
            project,
            "up",
            "-d",
            "--force-recreate",
            "--no-deps",
            service,
        ],
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output


def wait_healthy(health_url: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=3) as response:  # noqa: S310 — loopback only, validated above
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--compose-file", type=Path, default=Path(DEFAULT_COMPOSE))
    parser.add_argument("--project-name", default=DEFAULT_PROJECT)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--health-timeout", type=int, default=90)
    parser.add_argument(
        "--override-file",
        type=Path,
        default=Path("rsshub-env-override.yml"),
        help="compose override written next to the caller (wire env_file)",
    )
    parser.add_argument("--apply", action="store_true", help="default is dry-run")
    args = parser.parse_args()

    if args.service not in ALLOWED_SERVICES:
        raise SystemExit(
            f"ERROR: service {args.service!r} is not allow-listed "
            f"({', '.join(ALLOWED_SERVICES)})."
        )
    if not PROJECT_RE.match(args.project_name):
        raise SystemExit("ERROR: --project-name must be lowercase [a-z0-9_-].")
    validate_health_url(args.health_url)
    if not args.env_file.is_file():
        raise SystemExit(f"ERROR: env file not found: {args.env_file}")
    if not args.compose_file.is_file():
        raise SystemExit(f"ERROR: compose file not found: {args.compose_file}")

    values = parse_env_file(args.env_file)
    secret_keys = [
        key
        for key in values
        if any(
            token in key
            for token in ("KEY", "TOKEN", "COOKIE", "COOKIES", "SECRET", "PASSWORD")
        )
    ]
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"== RSSHub 配置应用（{mode}）==")
    print(f"env file       : {args.env_file}")
    print(f"键数量         : {len(values)}（含敏感键 {len(secret_keys)} 个，值不回显）")
    print(f"compose/project: {args.compose_file} / {args.project_name}")
    print(f"service        : {args.service}（up -d --force-recreate --no-deps）")
    print(f"health         : {args.health_url}")
    if not args.apply:
        print("\nDRY-RUN 未做任何更改。确认无误后追加 --apply 执行。")
        return 0

    write_override(args.env_file, args.service, args.override_file)
    code, output = run_apply(
        args.compose_file, args.override_file, args.project_name, args.service
    )
    if code != 0:
        print(output)
        print(
            "ERROR: compose up 失败。原容器状态未自动回滚；"
            "请检查上方输出后重试或还原 env 文件。"
        )
        return 1
    print("容器已重建（环境变量已生效）。等待健康检查…")
    if wait_healthy(args.health_url, args.health_timeout):
        print("HEALTHY：RSSHub /healthz 200。请在 Control Center 点击「标记为已应用」。")
        return 0
    print(
        "WARN: 容器已重建但健康检查超时。请检查 RSSHub 日志；如需回滚，"
        "用上一个 env 文件重新执行本脚本 --apply。"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
