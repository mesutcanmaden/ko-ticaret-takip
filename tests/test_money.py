from decimal import Decimal

import pytest

from app.core.errors import MoneyError
from app.core.money import (
    distribute, evaluate_offer, fmt_gb, fmt_gb_m, fmt_rate, gb_number, min_sale_price, net_amount,
    parse_decimal, parse_gb, parse_gb_m, parse_m, parse_tax_rate, slice_cost, split_gb_m, tax_amount,
)
from tests.conftest import GB, M


@pytest.mark.parametrize("text,expected", [
    ("12,5", 1_250_000_000), ("12.5", 1_250_000_000), ("12", 12 * GB), (" 12,50 ", 1_250_000_000),
    ("0,01", 1_000_000), (",5", 50_000_000), ("12,", 12 * GB), ("1.250,5", 125_050_000_000),
    ("1,250.5", 125_050_000_000), ("1.250.000", 125_000_000_000_000), ("0,00000001", 1), ("+3", 3 * GB),
])
def test_parse_gb(text, expected):
    assert parse_gb(text) == expected


@pytest.mark.parametrize("bad", ["", "  ", "-5", "abc", "12,5,1", "1,2.3,4", "0,000000001", "12.5.1", "1.25.000", "1.500", "12.500",
                                 "5e3", "1/2"])
def test_parse_gb_invalid(bad):
    with pytest.raises(MoneyError):
        parse_gb(bad)


def test_two_methods_equal():
    assert parse_gb("12,5") == parse_gb_m("12", "50") == 1_250_000_000
    assert parse_gb_m("", "350") == 350 * M
    assert parse_gb_m("3", "") == 3 * GB
    assert parse_m("0,5") == 500_000
    with pytest.raises(MoneyError):
        parse_gb_m("", "")
    with pytest.raises(MoneyError):
        parse_m("0,0000001")  # M'de 6 ondalıktan fazlası Noah altı


def test_format():
    assert gb_number(1_250_000_000) == "12,5"
    assert gb_number(123_456 * GB) == "123.456"
    assert fmt_gb(-45_000_000) == "-0,45 GB"
    assert fmt_gb(455_000_000, signed=True) == "+4,55 GB"
    assert fmt_gb(1) == "0,00000001 GB"
    assert fmt_gb_m(1_250_000_000) == "12 GB 50 M"
    assert fmt_gb_m(500_000) == "0,5 M"
    assert fmt_gb_m(3 * GB) == "3 GB"
    assert split_gb_m(1_250_500_000) == ("12", "50,5")
    # gidiş-dönüş
    for v in [0, 1, 12345678901, 99 * GB + 99 * M + 999_999]:
        assert parse_gb(gb_number(v)) == v
        g, m = split_gb_m(v)
        assert parse_gb_m(g, m or "0") == v


def test_decimal_no_float():
    assert parse_decimal("0,1") + parse_decimal("0,2") == Decimal("0.3")


def test_tax():
    assert tax_amount(15 * GB, 300) == 45_000_000  # 0,45 GB
    assert net_amount(15 * GB, "market", 300) == 1_455_000_000
    assert net_amount(15 * GB, "trade", 300) == 15 * GB
    # yarım-yukarı yuvarlama: 50 Noah * %3 = 1,5 -> 2 ; 49 * %3 = 1,47 -> 1
    assert tax_amount(50, 300) == 2
    assert tax_amount(49, 300) == 1
    assert tax_amount(0, 300) == 0


def test_tax_rate_parse():
    assert parse_tax_rate("3") == 300
    assert parse_tax_rate("%3,5") == 350
    assert parse_tax_rate("0") == 0
    assert fmt_rate(350) == "%3,5"
    assert fmt_rate(300) == "%3"
    for bad in ["100", "3,125", "-1", "x"]:
        with pytest.raises(MoneyError):
            parse_tax_rate(bad)


def test_min_sale_price():
    p = min_sale_price(10 * GB, 2 * GB, "market", 300)
    assert net_amount(p, "market", 300) >= 12 * GB
    assert net_amount(p - 1, "market", 300) < 12 * GB
    assert p == 1_237_113_402  # ~12,37 GB
    assert min_sale_price(10 * GB, 2 * GB, "trade", 300) == 12 * GB
    assert min_sale_price(0, 0, "market", 300) == 0
    for bps in (0, 1, 300, 999, 5000):
        for cost in (1, 7, 123_456_789, 10 * GB + 3):
            p = min_sale_price(cost, 5, "market", bps)
            assert net_amount(p, "market", bps) >= cost + 5
            assert p == 0 or net_amount(p - 1, "market", bps) < cost + 5


def test_offer():
    r = evaluate_offer(10 * GB, 15 * GB, "market", 300)
    assert r["profit"] == 455_000_000
    assert r["percent"] == Decimal("45.50")
    assert evaluate_offer(10 * GB, 15 * GB, "trade", 300)["profit"] == 5 * GB


def test_slice_and_distribute_exact():
    total, qty = 1000, 3
    parts = [slice_cost(total, qty, 0, 1), slice_cost(total, qty, 1, 1), slice_cost(total, qty, 2, 1)]
    assert sum(parts) == total
    assert slice_cost(10 * GB * 4, 4, 1, 2) == 20 * GB
    d = distribute(100, [1, 1, 1])
    assert sum(d) == 100 and sorted(d) == [33, 33, 34]
    assert distribute(15 * GB, [15 * GB]) == [15 * GB]
    assert distribute(10, [0, 0]) == [5, 5]
    assert distribute(0, [3, 4]) == [0, 0]


def test_m_only_input():
    from app.core.money import m_number
    assert parse_m("105") == 105 * M == parse_gb("1,05")
    assert parse_m("1500") == parse_m("1.500.000") // 1000 == 15 * GB
    assert parse_m("0.500") == 500_000  # baştaki 0 ile belirsiz değil
    with pytest.raises(MoneyError):
        parse_m("1.500")  # belirsiz -> uyarı
    assert parse_m("0,5") == 500_000
    assert m_number(105 * M) == "105" and m_number(500_000) == "0,5" and m_number(15 * GB) == "1500"
    for v in (1, 105 * M, 123_456_789):
        assert parse_m(m_number(v)) == v
