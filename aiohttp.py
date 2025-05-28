class ClientSession:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        pass
    async def get(self, *a, **k):
        class Resp:
            async def text(self):
                return ''
        return Resp()
