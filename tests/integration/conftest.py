import os
from uuid import uuid4

import pytest


@pytest.fixture
def postgres_dsn():
    """每项真实数据库测试拥有独立schema，不修改其他测试或现有业务的数据。"""
    base = os.environ.get("MVS_TEST_POSTGRES_DSN")
    if not base:
        pytest.skip("需要真实PostgreSQL测试实例")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "mvs_test_" + uuid4().hex
    with psycopg.connect(base, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(base, options=f"-c search_path={schema}")
    finally:
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def s3_bucket():
    endpoint = os.environ.get("MVS_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("需要真实S3测试实例")
    import boto3

    client = boto3.client("s3", endpoint_url=endpoint)
    bucket = "mvs-test-" + uuid4().hex
    client.create_bucket(Bucket=bucket)
    try:
        yield client, bucket, endpoint
    finally:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                client.delete_object(Bucket=bucket, Key=item["Key"])
        client.delete_bucket(Bucket=bucket)
        client.close()
