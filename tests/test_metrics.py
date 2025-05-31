from helpers.metrics import sharpe, profit_factor, max_drawdown


def test_sharpe_positive():
    assert sharpe([100, 101, 102, 101]) > 0


def test_profit_factor():
    trades = [{"pnl": 5}, {"pnl": -2}]
    assert profit_factor(trades) == 2.5


def test_max_drawdown():
    assert max_drawdown([100, 90, 95]) == 10
