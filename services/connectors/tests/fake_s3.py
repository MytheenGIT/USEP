"""In-memory stand-in for the boto3 S3 client methods the connectors use."""
from __future__ import annotations

import io


class FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_put_prefix: str | None = None

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, **_):
        if self.fail_put_prefix and Key.startswith(self.fail_put_prefix):
            raise FakeClientError("InternalError")
        if IfNoneMatch == "*" and Key in self.objects:
            raise FakeClientError("PreconditionFailed")
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}
