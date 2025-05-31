import runpy
import sys
import types


def test_download_cli(tmp_path, monkeypatch):
    class DummyHTTP:
        def __init__(self, *a, **k):
            self.called = False

        def get_kline(self, **params):
            if self.called:
                return {"result": {"list": []}}
            self.called = True
            return {
                "result": {
                    "list": [
                        {
                            "start": params["start"],
                            "open": "1",
                            "high": "1",
                            "low": "1",
                            "close": "1",
                            "volume": "1",
                        }
                    ]
                }
            }

    dummy_mod = types.SimpleNamespace(HTTP=DummyHTTP)
    monkeypatch.setitem(sys.modules, "pybit.unified_trading", dummy_mod)
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(
        ReadTimeout=Exception, ConnectionError=Exception
    ))
    monkeypatch.setitem(sys.modules, "urllib3", types.SimpleNamespace(exceptions=types.SimpleNamespace(ProtocolError=Exception)))
    monkeypatch.setattr(sys, "argv", [
        "utils.download_klines",
        "--symbol", "BTCUSDT",
        "--month", "2025-01",
        "--data-dir", str(tmp_path),
    ])
    runpy.run_module("utils.download_klines", run_name="__main__")
    assert (tmp_path / "BTCUSDT_2025-01_kline5m.csv").exists()
