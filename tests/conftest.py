import sys
import types
import pytest

@pytest.fixture(autouse=True)
def stub_external_modules(monkeypatch):
    websockets = types.ModuleType('websockets')
    websockets.connect = lambda *a, **k: None
    sys.modules.setdefault('websockets', websockets)

    pybit = types.ModuleType('pybit')
    ut = types.ModuleType('pybit.unified_trading')
    class HTTP:
        def __init__(self, *a, **k):
            pass
        def set_leverage(self, *a, **k):
            pass
    ut.HTTP = HTTP
    exc = types.ModuleType('pybit.exceptions')
    class InvalidRequestError(Exception):
        pass
    exc.InvalidRequestError = InvalidRequestError
    pybit.unified_trading = ut
    pybit.exceptions = exc
    sys.modules.setdefault('pybit', pybit)
    sys.modules.setdefault('pybit.unified_trading', ut)
    sys.modules.setdefault('pybit.exceptions', exc)

    requests = types.ModuleType('requests')
    sys.modules.setdefault('requests', requests)
    urllib3 = types.ModuleType('urllib3')
    sys.modules.setdefault('urllib3', urllib3)
    yield
