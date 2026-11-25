"""启动独立临时依赖并执行真实Docker验收，退出时仅删除本次创建的容器。"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def docker(*args: str) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, errors="replace", timeout=60
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker操作超过60秒，请检查引擎或预先拉取镜像") from None
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:])
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minio-image", default="mvs-test-minio:0.0.1")
    parser.add_argument("--sandbox-image", default="python:3.12-slim")
    parser.add_argument("--report", default=".tools/docker-acceptance.xml")
    parser.add_argument("--coverage", action="store_true", help="采集本次测试的行/分支覆盖率")
    parser.add_argument(
        "pytest_args",
        nargs="*",
        default=[
            "tests/integration/test_external_storage.py",
            "tests/integration/test_control_postgres.py",
            "tests/integration/test_docker_sandbox.py",
            "tests/integration/test_cluster_runtime.py",
            "tests/integration/test_cluster_process.py",
        ],
    )
    args = parser.parse_args()
    containers = []
    prefix = "mvs-accept-" + uuid4().hex[:10]
    password = secrets.token_hex(16)
    environ = dict(os.environ)

    def start(suffix: str, image: str, port: int, options: list[str], command: list[str]) -> int:
        name = prefix + "-" + suffix
        containers.append(name)
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"mvs.acceptance={prefix}",
            "-p",
            f"127.0.0.1::{port}",
            *options,
            image,
            *command,
        )
        return int(docker("port", name, f"{port}/tcp").rsplit(":", 1)[1])

    try:
        print("Docker engine: " + docker("version", "--format", "{{.Server.Version}}"), flush=True)
        redis_port = start("redis", "redis:7-alpine", 6379, [], [])
        pg_port = start(
            "postgres",
            "postgres:16-alpine",
            5432,
            [
                "-e",
                "POSTGRES_USER=mvs",
                "-e",
                "POSTGRES_DB=mvs",
                "-e",
                "POSTGRES_PASSWORD=" + password,
            ],
            [],
        )
        s3_port = start(
            "s3",
            args.minio_image,
            9000,
            ["-e", "MINIO_ROOT_USER=mvsaccept", "-e", "MINIO_ROOT_PASSWORD=" + password],
            ["server", "/data"],
        )
        environ.update(
            MVS_TEST_REDIS_URL=f"redis://127.0.0.1:{redis_port}/0",
            MVS_TEST_POSTGRES_DSN=f"postgresql://mvs:{password}@127.0.0.1:{pg_port}/mvs",
            MVS_TEST_S3_ENDPOINT=f"http://127.0.0.1:{s3_port}",
            AWS_ACCESS_KEY_ID="mvsaccept",
            AWS_SECRET_ACCESS_KEY=password,
            AWS_DEFAULT_REGION="us-east-1",
            MVS_TEST_SANDBOX_IMAGE=args.sandbox_image,
        )
        import httpx
        import psycopg
        import redis

        deadline = time.monotonic() + 45
        ready = False
        while time.monotonic() < deadline:
            try:
                client = redis.Redis.from_url(environ["MVS_TEST_REDIS_URL"], socket_timeout=2)
                assert client.ping()
                client.close()
                with psycopg.connect(environ["MVS_TEST_POSTGRES_DSN"], connect_timeout=2) as db:
                    db.execute("SELECT 1")
                assert (
                    httpx.get(
                        environ["MVS_TEST_S3_ENDPOINT"] + "/minio/health/live", timeout=2
                    ).status_code
                    == 200
                )
                ready = True
                break
            except Exception:
                time.sleep(1)
        if not ready:
            raise RuntimeError("临时测试依赖未在45秒内就绪")
        print("独立 Redis、PostgreSQL、S3 已就绪；开始测试。", flush=True)
        root = Path(__file__).resolve().parents[1]
        coverage_args = (
            [
                "--cov=src/mvs",
                "--cov-branch",
                "--cov-report=term",
                "--cov-report=json:artifacts/tests/coverage.json",
            ]
            if args.coverage
            else []
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *args.pytest_args,
                "-q",
                "--junitxml",
                args.report,
                *coverage_args,
            ],
            env=environ,
            cwd=root,
        )
        return result.returncode
    finally:
        removed, cleanup_errors = 0, []
        for name in reversed(containers):
            try:
                # 用本次随机标签限定清理目标，绝不删除同机的其他业务容器。
                owned = docker(
                    "ps",
                    "-aq",
                    "--filter",
                    f"name=^/{name}$",
                    "--filter",
                    f"label=mvs.acceptance={prefix}",
                )
                if owned:
                    docker("rm", "-f", "-v", name)
                    removed += 1
            except (RuntimeError, OSError):
                cleanup_errors.append(name)
        print(
            json.dumps(
                {"temporary_containers_removed": removed, "cleanup_failed": cleanup_errors},
                ensure_ascii=False,
            ),
            flush=True,
        )
        if cleanup_errors:
            raise RuntimeError("临时容器清理失败：" + ", ".join(cleanup_errors))


if __name__ == "__main__":
    raise SystemExit(main())
