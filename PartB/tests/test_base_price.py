"""pricing/base_price.py against docs/pricing-constants.md (card B8)."""
import pytest

from pricing.base_price import base_dry, base_price, beta, load_constants, surge

C = load_constants()


def test_surge_is_part_as_formula():
    assert surge(2, 0, C) == 2.0
    assert surge(0, 0, C) == 0.7
    assert surge(9, 0, C) == 3.0
    assert surge(7, 3, C) == 2.3
    assert surge(1, 10, C) == 0.7


def test_beta():
    assert beta(4 / 3, 0, C) == pytest.approx(1.2)
    assert beta(0, 1.0, C) == 1.0
    assert beta(100, 0, C) == 1 + C["betaCap"]
    assert beta(2.0, 1.0, C) == pytest.approx(1 + (2.0 - C["uncertaintyWeight"]) * C["betaCoef"])


def test_base_price_is_the_formula():
    d, D, S, r, s = 8.42, 3, 5, 1.2, 0.4
    expected = (C["baseFee"] + C["perKm"] * d) * surge(D, S, C) * (1 + min(max(r - C["uncertaintyWeight"] * s, 0)
                                                                         * C["betaCoef"], C["betaCap"]))
    assert base_dry(d, C) == C["baseFee"] + C["perKm"] * d
    assert base_price(d, D, S, r, s, C) == round(expected, 2)
