def test_filters_block():
    from src.strategy.dca import SmartDCA
    assert not SmartDCA.allowed(0, "BTCUSDT", 4.0, adx=27, rsi=30, spread_z=1, vbd=0.1)

def test_cap():
    from src.strategy.dca import SmartDCA
    for n in range(3):
        assert SmartDCA.allowed(n, "ETHUSDT", 1, adx=10, rsi=25, spread_z=0, vbd=0)
    assert not SmartDCA.allowed(3, "ETHUSDT", 1, adx=10, rsi=25, spread_z=0, vbd=0)
