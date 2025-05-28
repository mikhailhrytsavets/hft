class Dummy:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def recv(self):
        return ''
    async def send(self, *a, **k):
        pass

def connect(*a, **k):
    return Dummy()
