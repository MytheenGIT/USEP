import io


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, **_):
        if IfNoneMatch == "*" and Key in self.objects:
            raise FakeClientError("PreconditionFailed")
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000, StartAfter=None):
        ks = [k for k in sorted(self.objects) if k.startswith(Prefix) and (not StartAfter or k > StartAfter)]
        return {"Contents": [{"Key": k} for k in ks[:MaxKeys]]}
