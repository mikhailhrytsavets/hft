from strategy.dca import SmartDCA


def test_step_distance():
    step1 = SmartDCA.next_price(100, 2, 1, "BTCUSDT", "LONG")
    assert step1 == 100 - SmartDCA.calc_step(1, 2, "BTCUSDT")


def test_cap_and_filters():
    assert not SmartDCA.allowed(0, "BTCUSDT", 6.0, adx=10, rsi=30, spread_z=0, vbd=0)
    assert not SmartDCA.allowed(0, "BTCUSDT", 4.0, adx=30, rsi=30, spread_z=0, vbd=0)
    assert SmartDCA.allowed(0, "BTCUSDT", 4.0, adx=10, rsi=30, spread_z=0, vbd=0)
