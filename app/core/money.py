"""Knight Online para sistemi.

Programdaki bütün tutarlar arka planda TAM SAYI Noah olarak tutulur.
    1 GB = 100.000.000 Noah
    1 M  =   1.000.000 Noah
Float hiçbir hesapta kullanılmaz; dönüşümler Decimal ile yapılır.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from .errors import MoneyError

NOAH_PER_GB = 100_000_000
NOAH_PER_M = 1_000_000
MAX_NOAH = 10 ** 16  # 100 milyon GB; makul üst sınır (taşma / yazım hatası koruması)

BPS_DENOM = 10_000  # vergi oranı "baz puan" olarak tutulur: %3 = 300

_ALLOWED = re.compile(r"^[0-9.,]+$")


# --------------------------------------------------------------------------- #
# Metin -> Decimal
# --------------------------------------------------------------------------- #
def _check_grouping(int_part: str, sep: str) -> str:
    """'1.250.000' gibi binlik ayraçlı yazımı doğrular ve ayraçları siler."""
    groups = int_part.split(sep)
    if not groups[0] or len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:]):
        raise MoneyError(
            f"'{int_part}' anlaşılamadı. Binlik ayraç kullanacaksanız 3'erli gruplayın "
            f"(örn. 1.250), ya da hiç ayraç kullanmayın."
        )
    return "".join(groups)


def parse_decimal(text: str, field: str = "Tutar") -> Decimal:
    """Türkçe ve İngilizce yazımları güvenle Decimal'e çevirir.

    Kurallar:
      * Virgül ondalık ayırıcıdır: 12,5  -> 12.5
      * Tek nokta da ondalık kabul edilir: 12.5 -> 12.5
        (ancak '1.500' gibi belirsiz yazımlar reddedilir ve kullanıcı uyarılır)
      * Hem nokta hem virgül varsa sondaki ondalık, diğeri binlik ayraçtır:
        1.250,5 -> 1250.5    1,250.5 -> 1250.5
      * Birden fazla nokta (virgülsüz) binlik ayraç sayılır: 1.250.000 -> 1250000
      * Negatif sayı, harf vb. kabul edilmez.
    """
    if text is None:
        raise MoneyError(f"{field} boş bırakılamaz.")
    s = str(text).strip().replace(" ", "").replace(" ", "").replace("_", "")
    if s.startswith("+"):
        s = s[1:]
    if not s:
        raise MoneyError(f"{field} boş bırakılamaz.")
    if s.startswith("-"):
        raise MoneyError(f"{field} negatif olamaz.")
    if not _ALLOWED.match(s):
        raise MoneyError(f"{field} için yalnızca rakam, virgül ve nokta kullanabilirsiniz: '{text}'")

    has_c, has_d = "," in s, "." in s
    if has_c and has_d:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        th = "." if dec == "," else ","
        if s.count(dec) > 1:
            raise MoneyError(f"{field} anlaşılamadı: '{text}'")
        int_part, frac = s.split(dec)
        int_part = _check_grouping(int_part, th)
    elif has_c:
        if s.count(",") > 1:
            raise MoneyError(f"{field} içinde birden fazla virgül var: '{text}'")
        int_part, frac = s.split(",")
    elif has_d:
        if s.count(".") > 1:
            int_part, frac = _check_grouping(s, "."), ""
        else:
            int_part, frac = s.split(".")
            if len(frac) == 3 and 1 <= len(int_part) <= 3 and not int_part.startswith("0"):
                # '1.500' hem 1,5 hem 1500 anlamına gelebilir; sessizce yanlış tutar almayalım.
                raise MoneyError(
                    f"'{text}' belirsiz: 1500 demek istiyorsanız noktasız ({int_part}{frac}), "
                    f"{int_part},{frac.rstrip('0') or '0'} demek istiyorsanız virgülle yazın."
                )
    else:
        int_part, frac = s, ""

    if int_part == "":
        int_part = "0"
    if not int_part.isdigit() or (frac and not frac.isdigit()):
        raise MoneyError(f"{field} anlaşılamadı: '{text}'")
    if len(int_part.lstrip("0")) > 12:
        raise MoneyError(f"{field} çok büyük: '{text}'")
    return Decimal(f"{int_part}.{frac or '0'}")


def _to_noah(value: Decimal, unit: int, field: str, unit_name: str, max_decimals: int) -> int:
    n = value * unit
    if n != n.to_integral_value():
        raise MoneyError(
            f"{field}: {unit_name} cinsinden en fazla {max_decimals} ondalık basamak girilebilir "
            f"(1 Noah hassasiyeti)."
        )
    n = int(n)
    if n > MAX_NOAH:
        raise MoneyError(f"{field} çok büyük.")
    return n


def parse_gb(text: str, field: str = "Tutar", allow_empty: bool = False) -> int:
    """'12,5' (GB) -> 1.250.000.000 Noah"""
    if allow_empty and (text is None or str(text).strip() == ""):
        return 0
    return _to_noah(parse_decimal(text, field), NOAH_PER_GB, field, "GB", 8)


def parse_m(text: str, field: str = "Tutar", allow_empty: bool = False) -> int:
    """'50' (M) -> 50.000.000 Noah"""
    if allow_empty and (text is None or str(text).strip() == ""):
        return 0
    return _to_noah(parse_decimal(text, field), NOAH_PER_M, field, "M", 6)


def parse_gb_m(gb_text: str, m_text: str, field: str = "Tutar") -> int:
    """GB ve M alanlarını birlikte okur. Boş alan 0 sayılır, ikisi birden boş olamaz."""
    gb_empty = gb_text is None or str(gb_text).strip() == ""
    m_empty = m_text is None or str(m_text).strip() == ""
    if gb_empty and m_empty:
        raise MoneyError(f"{field} boş bırakılamaz.")
    total = parse_gb(gb_text, f"{field} (GB)", allow_empty=True) + parse_m(
        m_text, f"{field} (M)", allow_empty=True
    )
    if total > MAX_NOAH:
        raise MoneyError(f"{field} çok büyük.")
    return total


# --------------------------------------------------------------------------- #
# Noah -> metin
# --------------------------------------------------------------------------- #
def _group(int_str: str) -> str:
    out = []
    while len(int_str) > 3:
        out.insert(0, int_str[-3:])
        int_str = int_str[:-3]
    out.insert(0, int_str)
    return ".".join(out)


def gb_number(noah: int, max_decimals: int = 8) -> str:
    """1.250.000.000 -> '12,5'  (Türkçe biçim, gereksiz sıfırlar atılır)."""
    noah = int(noah)
    neg = noah < 0
    d = Decimal(abs(noah)) / Decimal(NOAH_PER_GB)
    q = Decimal(1).scaleb(-max_decimals)
    d = d.quantize(q, rounding=ROUND_HALF_UP)
    s = f"{d:f}"
    if "." in s:
        int_part, frac = s.split(".")
        frac = frac.rstrip("0")
    else:
        int_part, frac = s, ""
    res = _group(int_part) + ("," + frac if frac else "")
    if neg and res not in ("0",):
        res = "-" + res
    return res


def fmt_gb(noah: int, signed: bool = False, max_decimals: int = 8) -> str:
    s = gb_number(noah, max_decimals)
    if signed and noah > 0:
        s = "+" + s
    return f"{s} GB"


def fmt_gb_m(noah: int) -> str:
    """1.250.000.000 -> '12 GB 50 M'"""
    noah = int(noah)
    sign = "-" if noah < 0 else ""
    n = abs(noah)
    gb, rem = divmod(n, NOAH_PER_GB)
    m = Decimal(rem) / Decimal(NOAH_PER_M)
    m_s = f"{m.normalize():f}".replace(".", ",") if rem else "0"
    if rem == 0:
        return f"{sign}{_group(str(gb))} GB"
    if gb == 0:
        return f"{sign}{m_s} M"
    return f"{sign}{_group(str(gb))} GB {m_s} M"


def fmt_noah(noah: int) -> str:
    noah = int(noah)
    return ("-" if noah < 0 else "") + _group(str(abs(noah))) + " Noah"


def m_number(noah: int) -> str:
    """105.000.000 Noah -> '105' (M cinsinden, binlik ayraçsız; giriş alanı için)."""
    m = Decimal(int(noah)) / Decimal(NOAH_PER_M)
    return f"{m.normalize():f}".replace(".", ",") if noah else "0"


def split_gb_m(noah: int) -> tuple[str, str]:
    """GB+M giriş alanlarını doldurmak için metin çifti döner."""
    gb, rem = divmod(int(noah), NOAH_PER_GB)
    m = Decimal(rem) / Decimal(NOAH_PER_M)
    m_s = f"{m.normalize():f}".replace(".", ",") if rem else ""
    return str(gb), m_s


# --------------------------------------------------------------------------- #
# Vergi
# --------------------------------------------------------------------------- #
def parse_tax_rate(text: str) -> int:
    """'%3' / '3' / '3,5' -> baz puan (300 / 350). En fazla 2 ondalık, 0 <= oran < 100."""
    s = str(text).strip().lstrip("%").strip()
    d = parse_decimal(s, "Vergi oranı")
    bps = d * 100
    if bps != bps.to_integral_value():
        raise MoneyError("Vergi oranı en fazla 2 ondalık basamak içerebilir (örn. 3,25).")
    bps = int(bps)
    if bps >= BPS_DENOM:
        raise MoneyError("Vergi oranı %100'den küçük olmalıdır.")
    return bps


def fmt_rate(bps: int) -> str:
    d = (Decimal(int(bps)) / 100).normalize()
    return "%" + f"{d:f}".replace(".", ",")


def tax_amount(gross: int, bps: int) -> int:
    """Vergi = brüt * oran, Noah düzeyinde YARIM-YUKARI yuvarlanır (tam sayı aritmetiği)."""
    gross, bps = int(gross), int(bps)
    if gross < 0 or bps < 0:
        raise MoneyError("Vergi hesabında negatif değer olamaz.")
    return (gross * bps + BPS_DENOM // 2) // BPS_DENOM


def sale_tax(gross: int, method: str, bps: int) -> int:
    return tax_amount(gross, bps) if method == "market" else 0


def net_amount(gross: int, method: str, bps: int) -> int:
    return int(gross) - sale_tax(gross, method, bps)


# --------------------------------------------------------------------------- #
# Hesaplama araçları
# --------------------------------------------------------------------------- #
def min_sale_price(cost: int, target_profit: int, method: str, bps: int) -> int:
    """Net kâr >= hedef olacak EN DÜŞÜK brüt satış fiyatı (Noah)."""
    required = int(cost) + int(target_profit)
    if required <= 0:
        return 0
    if method != "market" or bps == 0:
        return required
    g = -(-required * BPS_DENOM // (BPS_DENOM - bps))  # tavan bölme
    while g > 0 and net_amount(g - 1, method, bps) >= required:
        g -= 1
    while net_amount(g, method, bps) < required:
        g += 1
    return g


def round_up_to(noah: int, step: int) -> int:
    return -(-int(noah) // step) * step


def profit_percent(profit: int, cost: int) -> Decimal | None:
    if cost <= 0:
        return None
    return (Decimal(int(profit)) * 100 / Decimal(int(cost))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def fmt_percent(p: Decimal | None) -> str:
    if p is None:
        return "—"
    s = f"{p.normalize():f}".replace(".", ",")
    return ("+" if p > 0 else "") + "%" + s


def evaluate_offer(cost: int, offer: int, method: str, bps: int) -> dict:
    tax = sale_tax(offer, method, bps)
    net = int(offer) - tax
    profit = net - int(cost)
    return {
        "gross": int(offer),
        "tax": tax,
        "net": net,
        "cost": int(cost),
        "profit": profit,
        "percent": profit_percent(profit, cost),
    }


# --------------------------------------------------------------------------- #
# Maliyet dağıtımı yardımcıları (tam sayı, kayıpsız)
# --------------------------------------------------------------------------- #
def slice_cost(total: int, qty: int, consumed_before: int, k: int) -> int:
    """Toplam maliyeti 'total' olan 'qty' adetlik partiden, daha önce 'consumed_before'
    adet kullanılmışken 'k' adet daha kullanılırsa bu k adedin maliyeti.

    Kümülatif taban yöntemi: parti tamamen tükendiğinde dağıtılan maliyetlerin
    toplamı her zaman TAM OLARAK 'total' olur (Noah kaybı/fazlası yok).
    Alış partilerinde total = birim * adet olduğundan sonuç birim * k'ya eşittir.
    """
    return total * (consumed_before + k) // qty - total * consumed_before // qty


def distribute(total: int, weights: list[int]) -> list[int]:
    """'total' tutarını ağırlıklara orantılı, toplamı bozmadan dağıtır (en büyük kalan yöntemi)."""
    if not weights:
        return []
    if total <= 0:
        return [0] * len(weights)
    w_sum = sum(weights)
    if w_sum <= 0:
        weights = [1] * len(weights)
        w_sum = len(weights)
    base = [total * w // w_sum for w in weights]
    rems = [(total * w % w_sum, -i) for i, w in enumerate(weights)]
    left = total - sum(base)
    for _, neg_i in sorted(rems, reverse=True)[:left]:
        base[-neg_i] += 1
    return base
