# KO Ticaret Takip

Knight Online item alış, satış ve takas işlemlerinizi takip eden, internet gerektirmeyen Türkçe Windows programı.
Program oyuna bağlanmaz, oyun dosyalarına dokunmaz ve kendiliğinden hiçbir oyun işlemi yapmaz. Bütün kayıtları siz elle girersiniz.

---

## Kurulum (adım adım)

### 1. Python'u kurun (yalnızca bir kez)
1. https://www.python.org/downloads/ adresine gidin ve **Python 3.12** sürümünü indirin.
2. Kurulumun ilk ekranında alttaki **"Add python.exe to PATH"** kutusunu işaretleyin.
3. **Install Now**'a tıklayın ve kurulum bitene kadar bekleyin.

### 2. Program klasörünü açın
İndirdiğiniz `KOTicaretTakip.zip` dosyasına sağ tıklayın, **Tümünü ayıkla**'yı seçin. Örneğin `Belgeler\KOTicaretTakip` gibi bir klasöre çıkartın.

### 3. Kurulumu yapın (yalnızca bir kez)
Klasördeki **`1_kurulum.bat`** dosyasına çift tıklayın. Gerekli paketler internetten indirilir; bu birkaç dakika sürebilir.
"Kurulum tamamlandı" yazısını görünce pencereyi kapatabilirsiniz.

> Windows "Bilgisayarınız korundu" uyarısı verirse **Ek bilgi → Yine de çalıştır**'a tıklayın.

### 4a. Programı çalıştırın
**`2_calistir.bat`** dosyasına çift tıklayın.

### 4b. EXE dosyası oluşturun (önerilir)
**`3_exe_olustur.bat`** dosyasına çift tıklayın. Önce otomatik testler çalışır, ardından EXE oluşturulur.
Bittiğinde `dist` klasörü açılır. İçindeki **`KOTicaretTakip.exe`** dosyası tek başına çalışır:
masaüstünüze kopyalayabilir, Python kurulu olmayan başka bir bilgisayarda da açabilirsiniz.

---

## Verileriniz nerede?

Bütün veriler EXE'den bağımsız olarak şu klasörde saklanır:

```
%LOCALAPPDATA%\KOTicaretTakip\
    ticaret.db          ← veritabanı
    Yedekler\           ← otomatik ve manuel yedekler
    hata_kaydi.log      ← beklenmeyen hata olursa ayrıntılar
```

(Windows Gezgini'nin adres çubuğuna `%LOCALAPPDATA%\KOTicaretTakip` yazıp Enter'a basarak açabilirsiniz. Ayarlar > "Veri klasörünü aç" düğmesi de aynı klasörü açar.)
EXE'yi silmek veya taşımak verilerinizi etkilemez. Program ilk açılışta bu klasörleri kendisi oluşturur.

---

## Kullanım özeti

| Bölüm | Ne işe yarar |
|---|---|
| **Ana Sayfa** | Kullanılabilir GB, kâr/zarar, stok, son işlemler. Bugün / Bu Hafta / Bu Ay / Tüm Zamanlar filtresi. Hızlı düğmeler: Item Al, Item Sat, Takas, GB Ekle, GB Çıkar, Son İşlemi Geri Al |
| **Item Al** | Item adı + upgrade + adet + birim fiyat. "Sha" yazınca daha önce girilen "Shard +8" önerilir. "Shard +8" veya "Shard Reb3" yazarsanız seviye kendiliğinden upgrade listesinde seçilir |
| **Item Sat** | *Satış* sekmesi: item, parti (varsayılan en eski), adet, fiyat, Pazar/Trade. Kaydetmeden önce net kâr gösterilir. *Takas* sekmesi: item ↔ item (+ GB) takası |
| **Stoklarım** | Item başına toplam adet, ortalama maliyet, durum, bekleme süresi. Seçilen item için alış partileri, satışa çıkarma, fiyat geçmişi ve grafik |
| **İşlem Geçmişi** | Arama, tür ve tarih filtresi, kâra göre sıralama. Detay / Düzenle / Sil |
| **İstatistikler** | Kâr-zarar grafiği, en kârlı ve en çok zarar ettiren itemler, ortalama satış süresi |
| **Hesaplama Araçları** | Hedef satış fiyatı ve teklif hesaplayıcı (kayıt oluşturmaz) |
| **Ayarlar** | Vergi oranı, fiyat giriş yöntemi, başlangıç GB, yedekleme ve geri yükleme |

Kısayollar: **Ctrl+1 … Ctrl+8** menü bölümleri arasında geçiş yapar. Fiyat veya açıklama alanında **Enter** kaydeder.

### Upgrade seviyesi
Açılır listeden seçilir: **Yok**, düz itemler için **+1 … +10**, rebirth itemler için **Reb1 … Reb21**.
Aynı item adının her seviyesi ayrı ürün olarak takip edilir (örn. "Kılıç +3" ile "Kılıç Reb3" ayrı stoklardır).

### Fiyat girişi
* **Varsayılan: M ile giriş.** `105` yazarsanız 105 M (= 1,05 GB) olur; alanın yanında GB karşılığı gösterilir.
  `1500` → 15 GB, `0,5` → 0,5 M.
* Fiyat alanının yanındaki `⇄` düğmesi giriş yöntemini sırayla değiştirir:
  **M** (`105`) → **ondalıklı GB** (`1,05`) → **GB + M ayrı alanlar** (GB `1`, M `5`). Üçü de aynı tutarı ifade eder.
* Varsayılan yöntemi Ayarlar → "Varsayılan fiyat giriş yöntemi" bölümünden değiştirebilirsiniz.
* Binlik ayraç kullanmayın: `1.500` gibi bir yazım hem 1,5 hem 1500 anlamına gelebileceği için program uyarı verir;
  `1500` veya `1,5` yazın.
* 1 GB = 100.000.000 Noah, 1 M = 1.000.000 Noah. Bütün hesaplar arka planda tam sayı Noah ile yapılır (yuvarlama hatası olmaz).
* Hatalı girişte alan kırmızı olur, kaydederken açıklayıcı uyarı çıkar.

### Kâr nasıl hesaplanır?
* **Net kâr = Net satış tutarı − satılan itemin GERÇEK alış maliyeti** (seçilen partinin maliyeti).
* Pazar satışı: vergi (varsayılan %3) satış fiyatından düşülür; vergi Noah düzeyinde yarım-yukarı yuvarlanır.
* Trade satışı: vergi yoktur.
* Her satışın vergi oranı satışla birlikte kaydedilir; Ayarlar'dan oranı değiştirmek eski satışları değiştirmez.
* Stoktaki ve satışta bekleyen itemler kâr sayılmaz. GB Ekle / GB Çıkar kâr sayılmaz.
* Ortalama alış fiyatı yalnızca bilgi amaçlıdır.

### Takas maliyet yöntemi
Verilen itemlerin gerçek maliyeti + verdiğiniz GB − aldığınız GB = **alınan itemlere aktarılan maliyet**.
Bu tutar, alınan itemlere girdiğiniz "anlaşılan değer" oranında dağıtılır. Takas tek başına kâr üretmez; kâr/zarar alınan item satıldığında oluşur.
Örnek: 20 GB maliyetli item verip 15 GB değerli item + 5 GB aldınız → yeni itemin maliyeti 15 GB, kâr 0.
(İstisna: aldığınız GB, verdiklerinizin toplam maliyetinden fazlaysa aradaki fark kâr olarak kaydedilir. Hiç item almadıysanız takas, item karşılığı GB satışı gibi hesaplanır.)
Kaydetmeden önce bütün bu sonuçlar ekranda gösterilir.

### Satışa çıkarma
Stoklarım → item seçin → partiyi seçin → **Satışa çıkar…**. Satışa çıkarılan item stoktan düşmez, yalnızca satış tamamlanınca düşer. İlan fiyatı kaydedilmez.
Pazar satışı önce "satışta" olan adetlerden, Trade satışı önce "stokta" olan adetlerden düşer.

### Düzenleme, silme, geri alma
* **Alış** düzenlenebilir: adet, fiyat, tarih, not (o partiden satış yapılmadıysa item adı da). Fiyat değişirse bağlı satışların kârı ve takasla gelen itemlerin maliyeti otomatik güncellenir.
* **Satış** düzenlenebilir: fiyat, yöntem, vergi oranı, tarih, not. *Satılan adet veya parti değişecekse satışı silip yeniden girin.*
* **Takas** düzenlenebilir: tarih ve not. *İçeriği değişecekse takası silip yeniden girin.*
* **GB hareketi** düzenlenebilir: miktar, tarih, açıklama.
* Bir kaydı silmek/geri almak stoğu eksiye düşürecekse (örn. itemi satılmış bir alış) program izin vermez ve hangi işlemlerin önce silinmesi gerektiğini söyler.
* Her değişiklikten sonra bütün stok, maliyet, kâr ve bakiye hesapları kayıtlardan baştan kurulur; tutarsızlık oluşamaz.

### Yedekleme
* Son başarılı yedekten 3 gün sonra programın ilk açılışında otomatik yedek alınır. Son 10 yedek saklanır.
* Ayarlar → **Şimdi yedek al** / **Seçili yedeği geri yükle** / **Dosyadan geri yükle…**
* Geri yüklemeden önce mevcut verilerin "geri_yukleme_oncesi_…" adıyla güvenlik yedeği otomatik alınır.
* Yedek alınamazsa program çalışmaya devam eder, size uyarı gösterilir.

---

## Teknik bilgiler (geliştiriciler için)

```
main.py                    Başlatıcı (hata yakalama, ilk kurulum, otomatik yedek)
app/core/money.py          Noah/GB dönüşümleri (Decimal), vergi, hesaplama araçları
app/core/db.py             SQLite şeması, transaction yönetimi
app/core/ledger.py         Yeniden hesaplama motoru (kronolojik oynatma)
app/core/service.py        İş mantığı – arayüz yalnızca bunu kullanır
app/core/backup.py         Yedekleme / geri yükleme (SQLite online backup API)
app/core/paths.py          Kullanıcı veri klasörü
app/ui/                    PySide6 arayüzü (theme, widgets, dialogs, pages/*)
tests/                     pytest testleri (para, işlemler, yedekleme, arayüz)
```

**Veritabanı tabloları:** `settings`, `item_names` (yeniden adlandırılabilir isimler), `products` (isim + upgrade),
`transactions` (bütün işlemler), `tx_notes`, `lots` (alış partileri), `consumptions` (satış/takas ↔ parti eşleştirmesi),
`listings` (satıştaki adetler).

**Tutarlılık modeli:** Kaynak veriler (işlemler, partiler, parti kullanımları) dışındaki her şey türetilmiştir ve her yazma
işleminden sonra aynı SQLite transaction'ı içinde `ledger.rebuild()` ile baştan hesaplanır. Kural ihlalinde (stok eksi,
satışın alıştan önce olması vb.) transaction tamamen geri alınır. Önizlemeler de aynı motorla, geri alınan bir transaction
içinde hesaplanır; bu yüzden önizleme ile kaydedilen sonuç her zaman aynıdır. Kısmi satışlarda maliyet, kümülatif tam sayı
dilimleme ile dağıtılır: bir parti tamamen tükendiğinde dağıtılan maliyet toplamı Noah'ı Noah'ına parti maliyetine eşittir.

**Testleri çalıştırma:** `testleri_calistir.bat` (veya `.venv\Scripts\python -m pytest -v`).
`tests/test_ui_smoke.py`, gerçek PySide6 ile pencereyi ekransız açıp alış, satış, takas, geri alma ve yedekleme yapar.

**Elle EXE oluşturma:**
```
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --onefile --name KOTicaretTakip --icon assets\icon.ico --add-data "assets;assets" main.py
```
