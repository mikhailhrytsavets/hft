async def connect(*a, **k):
    class DB:
        async def execute(self, *a, **k):
            pass
        async def close(self):
            pass
    return DB()
