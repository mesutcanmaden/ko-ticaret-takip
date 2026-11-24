"""Kullanıcıya gösterilecek hata türleri."""


class UserError(Exception):
    """Kullanıcıya doğrudan gösterilebilecek, Türkçe mesajlı hata."""


class MoneyError(UserError):
    """Geçersiz para girişi."""


class LedgerError(UserError):
    """Stok / maliyet / bakiye tutarlılığını bozacak bir işlem."""
