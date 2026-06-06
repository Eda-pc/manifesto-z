import streamlit as st
from groq import Groq
import json, sqlite3, os
from datetime import datetime

# ============================================================
# AYARLAR
# ============================================================
API_KEY = st.secrets["GROQ_API_KEY"]
MECLIS_OY_ESIGI  = 25          # demo için 25, gerçekte 2500
ADMIN_SIFRE      = "esenler2025"
ADMIN_KULLANICI  = "esenler_admin"
DB_PATH          = "manifesto.db"

groq_client = Groq(api_key=API_KEY)

# ============================================================
# VERİTABANI — SQLite
# ============================================================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS kullanicilar (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ad        TEXT NOT NULL,
        sehir     TEXT DEFAULT 'Esenler',
        puan      INTEGER DEFAULT 0,
        rozet     TEXT DEFAULT '[]',
        tarih     TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS onergeler (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_id  INTEGER,
        yazar         TEXT,
        ham           TEXT NOT NULL,
        baslik        TEXT,
        gerekce       TEXT,
        yasal_dayanak TEXT,
        tahmini_maliyet TEXT,
        ilgili_birim  TEXT,
        oncelik_skoru INTEGER DEFAULT 7,
        oy            INTEGER DEFAULT 0,
        kategori      TEXT,
        alt_kategori  TEXT,
        durum         TEXT DEFAULT 'beklemede',
        admin_yanit   TEXT DEFAULT '',
        karbon        REAL DEFAULT 0.0,
        onbellekten   INTEGER DEFAULT 0,
        tarih         TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(kullanici_id) REFERENCES kullanicilar(id)
    );
    CREATE TABLE IF NOT EXISTS oylar (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        onerge_id    INTEGER,
        kullanici_id INTEGER,
        tarih        TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(onerge_id, kullanici_id)
    );
    CREATE TABLE IF NOT EXISTS odul_talepleri (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_id INTEGER,
        kullanici_ad TEXT,
        odul_ad      TEXT,
        durum        TEXT DEFAULT 'beklemede',
        tarih        TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS puan_hareketleri (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kullanici_id INTEGER,
        miktar       INTEGER,
        sebep        TEXT,
        tarih        TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    c.commit()
    c.close()

db_init()

# ============================================================
# DB YARDIMCI FONKSİYONLAR
# ============================================================
def kullanici_kaydet(ad, sehir):
    c = db()
    cur = c.execute("INSERT INTO kullanicilar (ad, sehir) VALUES (?,?)", (ad, sehir))
    kid = cur.lastrowid
    c.commit(); c.close()
    return kid

def kullanici_getir(kid):
    c = db()
    row = c.execute("SELECT * FROM kullanicilar WHERE id=?", (kid,)).fetchone()
    c.close()
    return dict(row) if row else None

def puan_guncelle(kid, miktar, sebep):
    c = db()
    c.execute("UPDATE kullanicilar SET puan=puan+? WHERE id=?", (miktar, kid))
    c.execute("INSERT INTO puan_hareketleri (kullanici_id,miktar,sebep) VALUES (?,?,?)", (kid, miktar, sebep))
    c.commit(); c.close()

def rozet_guncelle(kid, rozetler):
    c = db()
    c.execute("UPDATE kullanicilar SET rozet=? WHERE id=?", (json.dumps(rozetler, ensure_ascii=False), kid))
    c.commit(); c.close()

def onerge_ekle(kid, yazar, ham, resmi, kategori, alt_kat, karbon, onbellekten):
    c = db()
    cur = c.execute("""INSERT INTO onergeler
        (kullanici_id,yazar,ham,baslik,gerekce,yasal_dayanak,tahmini_maliyet,
         ilgili_birim,oncelik_skoru,kategori,alt_kategori,karbon,onbellekten)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (kid, yazar, ham,
         resmi["baslik"], resmi["gerekce"], resmi["yasal_dayanak"],
         resmi["tahmini_maliyet"], resmi["ilgili_birim"], resmi["oncelik_skoru"],
         kategori, alt_kat, karbon, int(onbellekten)))
    oid = cur.lastrowid
    c.commit(); c.close()
    return oid

def onergeler_getir(siralama="oy", kat_filtre=None, arama=None):
    c = db()
    q = "SELECT * FROM onergeler WHERE 1=1"
    params = []
    if kat_filtre and kat_filtre != "Tümü":
        q += " AND kategori=?"; params.append(kat_filtre)
    if arama:
        q += " AND (ham LIKE ? OR baslik LIKE ?)"; params += [f"%{arama}%", f"%{arama}%"]
    order = {"oy": "oy DESC", "yeni": "id DESC", "meclis": "oy DESC"}.get(siralama, "oy DESC")
    q += f" ORDER BY {order}"
    rows = c.execute(q, params).fetchall()
    c.close()
    result = [dict(r) for r in rows]
    if siralama == "meclis":
        result = [r for r in result if r["oy"] >= MECLIS_OY_ESIGI]
    return result

def oy_ver(onerge_id, kullanici_id):
    c = db()
    try:
        c.execute("INSERT INTO oylar (onerge_id,kullanici_id) VALUES (?,?)", (onerge_id, kullanici_id))
        c.execute("UPDATE onergeler SET oy=oy+1 WHERE id=?", (onerge_id,))
        c.commit(); c.close()
        return True
    except sqlite3.IntegrityError:
        c.close(); return False   # zaten oy verilmiş

def onerge_guncelle(oid, durum=None, yanit=None):
    c = db()
    if durum: c.execute("UPDATE onergeler SET durum=? WHERE id=?", (durum, oid))
    if yanit is not None: c.execute("UPDATE onergeler SET admin_yanit=? WHERE id=?", (yanit, oid))
    c.commit(); c.close()

def odul_talep_ekle(kid, kad, odul_ad):
    c = db()
    c.execute("INSERT INTO odul_talepleri (kullanici_id,kullanici_ad,odul_ad) VALUES (?,?,?)", (kid, kad, odul_ad))
    c.commit(); c.close()

def odul_talepleri_getir():
    c = db()
    rows = c.execute("SELECT * FROM odul_talepleri ORDER BY id DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]

def odul_talep_onayla(talep_id):
    c = db()
    c.execute("UPDATE odul_talepleri SET durum='teslim edildi' WHERE id=?", (talep_id,))
    c.commit(); c.close()

def istatistik_getir():
    c = db()
    toplam   = c.execute("SELECT COUNT(*) FROM onergeler").fetchone()[0]
    bekleyen = c.execute("SELECT COUNT(*) FROM onergeler WHERE durum='beklemede'").fetchone()[0]
    meclis   = c.execute(f"SELECT COUNT(*) FROM onergeler WHERE oy>={MECLIS_OY_ESIGI}").fetchone()[0]
    toplam_oy= c.execute("SELECT SUM(oy) FROM onergeler").fetchone()[0] or 0
    karbon   = c.execute("SELECT SUM(karbon) FROM onergeler").fetchone()[0] or 0.0
    onbellekten = c.execute("SELECT COUNT(*) FROM onergeler WHERE onbellekten=1").fetchone()[0]
    kat_dag  = c.execute("SELECT kategori,COUNT(*) as sayi FROM onergeler GROUP BY kategori ORDER BY sayi DESC").fetchall()
    c.close()
    return {"toplam":toplam,"bekleyen":bekleyen,"meclis":meclis,
            "toplam_oy":toplam_oy,"karbon":karbon,"onbellekten":onbellekten,
            "kat_dag":[dict(r) for r in kat_dag]}

# ============================================================
# SABITLER
# ============================================================
ODULLER = [
    {"puan":100,  "emoji":"🏊","ad":"Yüzme Havuzu Girişi",             "tur":"Tesis",    "aciklama":"Esenler Millet Bahçesi havuzuna 1 seferlik ücretsiz giriş"},
    {"puan":200,  "emoji":"💪","ad":"Fitness Salonu Günlük Giriş",      "tur":"Tesis",    "aciklama":"Gençlik Merkezi fitness salonuna 1 günlük ücretsiz erişim"},
    {"puan":300,  "emoji":"🎮","ad":"E-Spor Salonu 2 Saatlik Kullanım", "tur":"Tesis",    "aciklama":"E-spor salonunda 2 saatlik ücretsiz oyun süresi"},
    {"puan":400,  "emoji":"🎒","ad":"Kültür Gezisi Önceliği",           "tur":"Etkinlik", "aciklama":"Belediye kültür gezilerine öncelikli kayıt hakkı"},
    {"puan":500,  "emoji":"📚","ad":"Yazılımcı Fabrikası Kursu",        "tur":"Eğitim",   "aciklama":"Yazılımcı Fabrikası'nda 1 aylık ücretsiz kurs"},
    {"puan":600,  "emoji":"⛺","ad":"Yaz Kampı Katılım Hakkı",          "tur":"Etkinlik", "aciklama":"Esenler yaz kampına ücretsiz katılım"},
    {"puan":750,  "emoji":"🎧","ad":"Kablosuz Kulaklık",                "tur":"Hediye",   "aciklama":"Bluetooth kulaklık"},
    {"puan":900,  "emoji":"🎒","ad":"Kamp Çantası & Ekipman Seti",      "tur":"Hediye",   "aciklama":"Outdoor kamp çantası ve ekipman seti"},
    {"puan":1100, "emoji":"📱","ad":"Akıllı Saat",                      "tur":"Hediye",   "aciklama":"Spor odaklı akıllı saat"},
    {"puan":1500, "emoji":"💻","ad":"Tablet Bilgisayar",                "tur":"Hediye",   "aciklama":"Eğitim amaçlı tablet"},
    {"puan":2000, "emoji":"🏆","ad":"Başkan ile Özel Buluşma",          "tur":"Onur",     "aciklama":"Belediye Başkanı ile özel buluşma & sertifika"},
]

ETKINLIK_PUANLARI = [
    {"etkinlik":"🗳️ Önerge Yaz","puan":50},
    {"etkinlik":"👍 Başkasını Oyla","puan":10},
    {"etkinlik":"🏊 Havuza Git (QR)","puan":30},
    {"etkinlik":"⚽ Halı Saha Etkinliği","puan":40},
    {"etkinlik":"🎒 Geziye Katıl","puan":80},
    {"etkinlik":"💻 Yazılımcı Fabrikası","puan":60},
    {"etkinlik":"🎭 Kültür Sanat Etkinliği","puan":35},
    {"etkinlik":"🌱 Gönüllü Faaliyet","puan":70},
    {"etkinlik":"🏆 Turnuvaya Katıl","puan":90},
    {"etkinlik":"📋 Anket/Geri Bildirim","puan":20},
]

KATEGORILER = {
    "⚽ Spor":              {"aciklama":"Spor tesisleri, kulüpler, etkinlikler",
                             "altlar":["Halı Saha & Basketbol","Yüzme & Havuz","Fitness & Spor Salonu","Amatör Spor Kulüpleri","Spor Turnuvaları","Bisiklet & Koşu"]},
    "🎭 Kültür & Sanat":   {"aciklama":"Konser, sergi, tiyatro, festival",
                             "altlar":["Konser & Müzik","Tiyatro & Gösteri","Sergi & Müze","Festival & Şenlik","Sanat Atölyeleri","Sinema"]},
    "🌳 Park & Çevre":     {"aciklama":"Parklar, yeşil alanlar, çevre düzenlemesi",
                             "altlar":["15 Temmuz Millet Bahçesi","Mahalle Parkları","Yeşil Alan & Ağaçlandırma","Çevre Temizliği","Geri Dönüşüm","İklim & Sürdürülebilirlik"]},
    "🎓 Eğitim & Gençlik": {"aciklama":"Kurslar, gençlik merkezi, kariyer",
                             "altlar":["Yazılımcı Fabrikası","Mesleki Kurslar","Gençlik Merkezi","Kariyer & Staj","Burs & Destek","Yabancı Dil"]},
    "🚌 Ulaşım & Altyapı": {"aciklama":"Yollar, toplu taşıma, aydınlatma",
                             "altlar":["Yol & Kaldırım","Toplu Taşıma","Park & Otopark","Aydınlatma","Bisiklet Yolu","Engelli Erişimi"]},
    "🏥 Sağlık & Sosyal":  {"aciklama":"Sağlık, sosyal yardım, engelli hizmetleri",
                             "altlar":["Sağlık Taraması","Psikolojik Destek","Engelli Hizmetleri","Yaşlı Hizmetleri","Sosyal Yardım","Kadın & Aile"]},
    "🏗️ Kentsel Dönüşüm": {"aciklama":"Bina yenileme, kentsel tasarım",
                             "altlar":["Bina Yenileme","Mahalle Tasarımı","Boş Alan Değerlendirme","Tarihi Alan Koruma","Meydan Düzenlemesi","Duvar & Cephe"]},
    "🆘 Acil & Güvenlik":  {"aciklama":"Deprem, afet, güvenlik, itfaiye",
                             "altlar":["Deprem Hazırlık","Afet Toplanma Alanı","Güvenlik Kamerası","Yangın Güvenliği","İlk Yardım Eğitimi","Acil Durum Planı"]},
    "💻 Dijital & Teknoloji":{"aciklama":"Akıllı şehir, wifi, dijital hizmetler",
                             "altlar":["Ücretsiz Wi-Fi","Akıllı Şehir","E-Belediye Hizmetleri","Dijital Kütüphane","Kodlama & Robotik","Yapay Zeka Projeleri"]},
    "🎉 Etkinlik & Gezi":  {"aciklama":"Şehir gezileri, kamplar, gençlik etkinlikleri",
                             "altlar":["Yurt İçi Gezi","Yurt Dışı Gezi","Yaz Kampı","Kış Kampı","Gençlik Günleri","Mahalle Şenlikleri"]},
}

YASAK_KELIMELER = [
    "sik","orospu","piç","göt","amk","bok","salak","gerizekalı","aptal",
    "mal","şerefsiz","kahpe","ibne","öldür","vur","bomba","terör","saldır",
]

# ============================================================
# CSS
# ============================================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap');
html,body,[class*="css"]{font-family:'Nunito',sans-serif;}
.hero{background:linear-gradient(135deg,#0d1b2a 0%,#1b2d45 60%,#0f3460 100%);
  border-radius:22px;padding:36px 44px;margin-bottom:20px;border:1px solid rgba(255,255,255,0.07);}
.hero-title{font-size:2.6rem;font-weight:900;color:#fff;margin:0;}
.hero-slogan{font-size:1.4rem;font-weight:800;
  background:linear-gradient(90deg,#63b3ed,#a78bfa,#f687b3);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-top:4px;}
.hero-sub{color:#94a3b8;font-size:0.88rem;margin-top:6px;}
.stat-kart{background:linear-gradient(135deg,#1e293b,#0f172a);
  border:1px solid rgba(99,179,237,0.18);border-radius:18px;padding:20px;text-align:center;}
.stat-sayi{font-size:2.2rem;font-weight:900;color:#63b3ed;}
.stat-etiket{color:#94a3b8;font-size:0.8rem;margin-top:2px;}
.odul-kart{background:#0f172a;border-radius:14px;padding:14px 18px;margin-bottom:9px;
  border:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:14px;}
.odul-acik{border-color:rgba(99,179,237,0.5)!important;background:#1e3a5f!important;}
.odul-kilitli{opacity:0.38;}
.odul-ad{font-size:0.95rem;color:#e2e8f0;font-weight:700;}
.odul-tur{font-size:0.72rem;color:#718096;}
.odul-puan{font-size:0.75rem;color:#63b3ed;font-weight:800;}
.onerge-kart{background:#1e293b;border:1px solid rgba(255,255,255,0.07);border-radius:16px;padding:18px;margin-bottom:14px;}
.karbon-badge{background:rgba(52,211,153,0.12);border:1px solid rgba(52,211,153,0.3);
  border-radius:8px;padding:5px 12px;font-size:0.78rem;color:#6ee7b7;display:inline-block;margin-top:6px;}
.meclis-badge{background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.4);
  border-radius:8px;padding:4px 10px;font-size:0.78rem;color:#fbbf24;display:inline-block;}
.bilgi-kutu{background:rgba(99,179,237,0.1);border:1px solid rgba(99,179,237,0.3);
  border-radius:10px;padding:12px 16px;color:#93c5fd;font-size:0.85rem;margin:10px 0;}
.uyari-kutu{background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.35);
  border-radius:10px;padding:10px 16px;color:#fca5a5;font-size:0.85rem;margin-top:8px;}
.etkinlik-satir{background:#1e293b;border-radius:10px;padding:11px 16px;
  margin-bottom:7px;display:flex;justify-content:space-between;align-items:center;}
.puan-rozet{background:rgba(99,179,237,0.15);border-radius:20px;
  padding:2px 10px;color:#63b3ed;font-weight:800;font-size:0.82rem;}
.ilerleme-bar{background:#1e293b;border-radius:10px;height:9px;overflow:hidden;margin-top:6px;}
.ilerleme-ic{background:linear-gradient(90deg,#63b3ed,#7c3aed);height:100%;border-radius:10px;}
.profil-card{background:linear-gradient(135deg,#1e293b,#0f172a);
  border-radius:20px;padding:28px;border:1px solid rgba(99,179,237,0.15);}
.giris-kart{background:linear-gradient(135deg,#1e293b,#0f172a);
  border-radius:20px;padding:40px;border:1px solid rgba(99,179,237,0.2);}
.admin-kart{background:#1e293b;border-radius:14px;padding:16px;
  margin-bottom:10px;border:1px solid rgba(245,158,11,0.2);}
.kat-etiket{background:rgba(99,179,237,0.15);border-radius:6px;
  padding:1px 8px;color:#63b3ed;font-size:0.78rem;}
</style>
"""

# ============================================================
# SESSION STATE
# ============================================================
DEFAULTS = {
    "kullanici_id": None, "kullanici_ad": "", "kullanici_sehir": "Esenler",
    "admin_giris": False, "sayfa": "giris",
    "onbellekte": {}, "kurtarilan_api": 0,
    "secili_kat": list(KATEGORILER.keys())[0],
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def icerik_filtrele(metin):
    ml = metin.lower()
    for k in YASAK_KELIMELER:
        if k in ml:
            return False, "Uygunsuz ifade tespit edildi. Lütfen saygılı bir dil kullan."
    if len(metin.strip()) < 15:
        return False, "Fikrin çok kısa, lütfen daha fazla detay ver (en az 15 karakter)."
    if len(metin) > 1000:
        return False, "Fikrin çok uzun (max 1000 karakter)."
    return True, ""

def karbon_hesapla(n):
    return round((n * 9 * 1.15) / 3600 * 0.4 * 1000, 4)

def onerge_ai(metin):
    cached = st.session_state.onbellekte.get(metin[:80].lower())
    if cached:
        st.session_state.kurtarilan_api += 1
        return cached, 0
    prompt = f"""Sen Esenler Belediyesi resmi karar yazım asistanısın.
Kullanıcı fikri: "{metin}"
SADECE şu JSON formatında yanıt ver, başka hiçbir şey yazma:
{{"baslik":"resmi kısa başlık","gerekce":"2-3 cümle gerekçe",
"yasal_dayanak":"5393 sayılı Belediye Kanunu Madde 14/a",
"tahmini_maliyet":"Düşük/Orta/Yüksek — kısa açıklama",
"ilgili_birim":"İlgili Müdürlük","oncelik_skoru":7}}"""
    r = groq_client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role":"user","content":prompt}]
    )
    raw = r.choices[0].message.content.replace("```json","").replace("```","").strip()
    sonuc = json.loads(raw)
    st.session_state.onbellekte[metin[:80].lower()] = sonuc
    return sonuc, len(metin.split())*2+300

def rozet_kontrol_ve_guncelle(kid):
    k = kullanici_getir(kid)
    if not k: return
    rozetler = json.loads(k["rozet"])
    p, n = k["puan"], 0
    c = db()
    n = c.execute("SELECT COUNT(*) FROM onergeler WHERE kullanici_id=?", (kid,)).fetchone()[0]
    c.close()
    yeni = []
    if n >= 1  and "🌱 Tohumcu"         not in rozetler: yeni.append("🌱 Tohumcu")
    if p >= 300 and "🔊 Ses Getiren"    not in rozetler: yeni.append("🔊 Ses Getiren")
    if p >= 600 and "⚡ Aktif Vatandaş"  not in rozetler: yeni.append("⚡ Aktif Vatandaş")
    if n >= 3  and "🏛️ Meclis Yıldızı"   not in rozetler: yeni.append("🏛️ Meclis Yıldızı")
    if yeni:
        rozetler.extend(yeni)
        rozet_guncelle(kid, rozetler)
        st.balloons()
    return rozetler

def sonraki_odul(p):
    for o in ODULLER:
        if o["puan"] > p: return o
    return None

def ilerleme_goster(puan):
    son = sonraki_odul(puan)
    if not son: return
    onceki = max([0]+[o["puan"] for o in ODULLER if o["puan"] <= puan])
    aralik = son["puan"] - onceki
    oran = min(int((puan-onceki)/aralik*100),100) if aralik else 100
    st.markdown(f"""<div style="color:#94a3b8;font-size:0.85rem;margin-top:12px">
      Sonraki ödül: <b style="color:#63b3ed">{son['emoji']} {son['ad']}</b>
      — <b>{son['puan']-puan} puan</b> kaldı</div>
      <div class="ilerleme-bar"><div class="ilerleme-ic" style="width:{oran}%"></div></div>
    """, unsafe_allow_html=True)

# ============================================================
# SAYFA KURULUM
# ============================================================
st.set_page_config(page_title="Esenler Manifesto-Z", page_icon="🏙️", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

# ============================================================
# GİRİŞ SAYFASI
# ============================================================
if st.session_state.sayfa == "giris":
    st.markdown("""<div class="hero" style="text-align:center;padding:48px">
      <div class="hero-title">🏙️ Esenler Manifesto-Z</div>
      <div class="hero-slogan">✨ Söz Sizde, İş Bizde!</div>
      <div class="hero-sub">Gençlerin Sesi · Yapay Zekanın Kalemi · 🌿 Green AI</div>
    </div>""", unsafe_allow_html=True)

    gc, ac = st.columns(2, gap="large")
    with gc:
        st.markdown("""<div class="giris-kart">
          <div style="text-align:center;font-size:2.5rem">🏙️</div>
          <div style="text-align:center;font-size:1.2rem;font-weight:800;color:#e2e8f0;margin-bottom:20px">Giriş Yap</div>
        </div>""", unsafe_allow_html=True)
        ad    = st.text_input("Adın", placeholder="Adın Soyadın")
        sehir = st.text_input("Mahalleniz", value="Esenler")
        if st.button("🚀 Uygulamaya Gir", type="primary", use_container_width=True):
            if ad.strip():
                kid = kullanici_kaydet(ad.strip(), sehir)
                st.session_state.kullanici_id  = kid
                st.session_state.kullanici_ad  = ad.strip()
                st.session_state.kullanici_sehir = sehir
                st.session_state.sayfa = "ana"
                st.rerun()
            else:
                st.warning("Lütfen adını yaz!")
        st.caption("🔒 Bilgileriniz yerel veritabanında güvenle saklanır.")

    with ac:
        st.markdown("""<div class="giris-kart">
          <div style="text-align:center;font-size:2.5rem">🏛️</div>
          <div style="text-align:center;font-size:1.2rem;font-weight:800;color:#fbbf24;margin-bottom:20px">Yönetici Girişi</div>
        </div>""", unsafe_allow_html=True)
        admin_ad = st.text_input("Kullanıcı Adı", placeholder="Yönetici kullanıcı adı")
        pw       = st.text_input("Şifre", type="password")
        if st.button("🔐 Yönetici Paneline Gir", use_container_width=True):
            if admin_ad == ADMIN_KULLANICI and pw == ADMIN_SIFRE:
                st.session_state.admin_giris   = True
                st.session_state.kullanici_ad  = "Yönetici"
                st.session_state.sayfa = "admin"
                st.rerun()
            else:
                st.error("Hatalı kullanıcı adı veya şifre!")
        st.caption("Demo → Kullanıcı: `esenler_admin` · Şifre: `esenler2025`")
    st.stop()

# ============================================================
# HERO + NAV (giriş sonrası)
# ============================================================
kid = st.session_state.kullanici_id
k_bilgi = kullanici_getir(kid) if kid else None
puan   = k_bilgi["puan"]   if k_bilgi else 0
rozetler = json.loads(k_bilgi["rozet"]) if k_bilgi else []

st.markdown(f"""<div class="hero">
  <div class="hero-title">🏙️ Esenler Manifesto-Z</div>
  <div class="hero-slogan">✨ Söz Sizde, İş Bizde!</div>
  <div class="hero-sub">👤 Hoş geldin, <b>{st.session_state.kullanici_ad}</b>
  · 📍 {st.session_state.kullanici_sehir} · ⭐ {puan} puan · 🌿 Green AI</div>
</div>""", unsafe_allow_html=True)

sayfalar = [("🏠 Ana","ana"),("✍️ Önerge Yaz","onerge"),("👤 Profilim","profil"),("🗳️ Topluluk","topluluk")]
if st.session_state.admin_giris:
    sayfalar = [("🏠 Ana","ana"),("🗳️ Topluluk","topluluk"),("🔐 Yönetici","admin")]

cols = st.columns(len(sayfalar)+1)
for col,(label,sayfa) in zip(cols, sayfalar):
    if col.button(label, use_container_width=True,
                  type="primary" if st.session_state.sayfa==sayfa else "secondary"):
        st.session_state.sayfa = sayfa; st.rerun()
cols[-1].button("🚪 Çıkış", use_container_width=True,
    on_click=lambda: st.session_state.update({"sayfa":"giris","kullanici_id":None,"admin_giris":False,"kullanici_ad":""}))
st.markdown("<br>", unsafe_allow_html=True)

# ============================================================
# ANA SAYFA
# ============================================================
if st.session_state.sayfa == "ana":
    stats = istatistik_getir()
    c1,c2,c3,c4 = st.columns(4)
    for col,sayi,etiket in [
        (c1, puan,              "⭐ Toplam Puanın"),
        (c2, stats["toplam"],   "📋 Toplam Önerge"),
        (c3, stats["meclis"],   "🏛️ Meclise Giden"),
        (c4, stats["toplam_oy"],"👍 Toplam Oy"),
    ]:
        col.markdown(f"""<div class="stat-kart">
          <div class="stat-sayi">{sayi}</div>
          <div class="stat-etiket">{etiket}</div></div>""", unsafe_allow_html=True)

    if rozetler:
        st.markdown("<br>**🏅 Rozetlerin:** " + "  ".join(rozetler))
    ilerleme_goster(puan)

    st.markdown(f"""<br><div class="bilgi-kutu">
    🏛️ <b>Meclise Gönderilme Eşiği: {MECLIS_OY_ESIGI} oy</b><br>
    {MECLIS_OY_ESIGI} oy alan önergeleri Esenler Belediyesi Gençlik ve Spor Müdürlüğü'ne otomatik iletilir.
    </div>""", unsafe_allow_html=True)

    gundem = onergeler_getir("oy")[:3]
    if gundem:
        st.subheader("🔥 Gündem Önergeleri")
        for o in gundem:
            etiket = "🏛️ Meclise Gönderildi!" if o["oy"]>=MECLIS_OY_ESIGI else f"👍 {o['oy']} oy"
            kat_html = f'<span class="kat-etiket">{o["kategori"]}</span>' if o.get("kategori") else ""
            st.markdown(f"""<div class="onerge-kart">
              <b>#{o['id']} {o['baslik']}</b>
              <span style="float:right;color:#63b3ed">{etiket}</span><br>
              {kat_html}
              <span style="color:#94a3b8;font-size:0.82rem">{o['gerekce'][:100]}...</span>
            </div>""", unsafe_allow_html=True)

# ============================================================
# ÖNERGE YAZ
# ============================================================
elif st.session_state.sayfa == "onerge":
    st.markdown(f"""<div class="bilgi-kutu">
    📢 Fikrini günlük dilde yaz, yapay zeka resmi belediye kararına dönüştürsün.
    <b>{MECLIS_OY_ESIGI} oy</b> alan önergen Gençlik ve Spor Müdürlüğü'ne iletilir.
    Hakaret ve uygunsuz içerikler otomatik engellenir.
    </div>""", unsafe_allow_html=True)

    sol, sag = st.columns([1,1], gap="large")
    with sol:
        st.subheader("✍️ Fikrini Yaz")
        st.markdown("**📂 Kategori Seç**")
        kat_cols = st.columns(2)
        secili_kat = st.session_state.secili_kat
        for i,(kat,_) in enumerate(KATEGORILER.items()):
            if kat_cols[i%2].button(kat, key=f"kat_{kat}", use_container_width=True,
                                    type="primary" if secili_kat==kat else "secondary"):
                st.session_state.secili_kat = kat; st.rerun()

        bilgi = KATEGORILER[secili_kat]
        st.markdown(f'<div class="bilgi-kutu" style="margin:8px 0">{secili_kat} · {bilgi["aciklama"]}</div>',
                    unsafe_allow_html=True)
        alt_kat = st.selectbox("Alt Kategori", bilgi["altlar"])
        fikir   = st.text_area("Esenler için hayalin nedir?",
                    placeholder=f"{secili_kat} konusunda önerini yaz...", height=110)
        resim   = st.file_uploader("📸 Fotoğraf Ekle (isteğe bağlı)",
                    type=["jpg","jpeg","png","webp"])
        if resim:
            st.image(resim, use_container_width=True)

        if st.button("🚀 Önergeye Dönüştür", type="primary", use_container_width=True):
            gecerli, hata = icerik_filtrele(fikir)
            if not gecerli:
                st.markdown(f'<div class="uyari-kutu">🚫 {hata}</div>', unsafe_allow_html=True)
            else:
                with st.spinner("Yapay zeka resmi metni hazırlıyor..."):
                    try:
                        prompt_metin = f"Kategori: {secili_kat} > {alt_kat}\n{fikir}"
                        sonuc, tokens = onerge_ai(prompt_metin)
                        karbon = karbon_hesapla(tokens)
                        onerge_ekle(kid, st.session_state.kullanici_ad, fikir,
                                    sonuc, secili_kat, alt_kat, karbon, tokens==0)
                        puan_guncelle(kid, 50, "Önerge yazma")
                        rozet_kontrol_ve_guncelle(kid)
                        st.success("✅ Önergen kaydedildi! +50 puan 🎉")
                        st.rerun()
                    except json.JSONDecodeError:
                        st.error("Format hatası, tekrar dene.")
                    except Exception as e:
                        st.error(f"Hata: {e}")

    with sag:
        son_list = onergeler_getir("yeni")
        kendi = [o for o in son_list if o.get("kullanici_id")==kid]
        if kendi:
            o = kendi[0]
            st.subheader("📄 Son Önergen")
            st.markdown(f"**📌** {o['baslik']}")
            st.markdown(f"**📝** {o['gerekce']}")
            st.markdown(f"**⚖️** {o['yasal_dayanak']}")
            st.markdown(f"**💰** {o['tahmini_maliyet']}")
            st.markdown(f"**🏢** {o['ilgili_birim']}")
            st.markdown(f"**🎯** {'⭐'*o['oncelik_skoru']}")
            badge = ("♻️ Önbellekten — 0.000 gCO₂e ✅" if o["onbellekten"]
                     else f"🌿 {o['karbon']:.4f} gCO₂e · GES ile nötralize ✅")
            st.markdown(f'<div class="karbon-badge">{badge}</div>', unsafe_allow_html=True)
            st.markdown(f"""<div class="bilgi-kutu" style="margin-top:10px">
            🏛️ Bu önerge <b>{MECLIS_OY_ESIGI} oy</b> aldığında Gençlik ve Spor Müdürlüğü'ne iletilir.
            </div>""", unsafe_allow_html=True)
        else:
            st.info("Sol taraftan ilk önergeyi yaz! 🌱")

# ============================================================
# PROFİL
# ============================================================
elif st.session_state.sayfa == "profil":
    k_bilgi = kullanici_getir(kid)
    puan    = k_bilgi["puan"] if k_bilgi else 0
    rozetler= json.loads(k_bilgi["rozet"]) if k_bilgi else []

    sol, sag = st.columns([1,1], gap="large")
    with sol:
        st.subheader("👤 Profil Bilgileri")
        yeni_ad    = st.text_input("Adın", value=st.session_state.kullanici_ad)
        yeni_sehir = st.text_input("Mahalle", value=st.session_state.kullanici_sehir)
        if st.button("💾 Kaydet", type="primary"):
            c = db()
            c.execute("UPDATE kullanicilar SET ad=?,sehir=? WHERE id=?", (yeni_ad, yeni_sehir, kid))
            c.commit(); c.close()
            st.session_state.kullanici_ad    = yeni_ad
            st.session_state.kullanici_sehir = yeni_sehir
            st.success("Profil güncellendi!")

        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("🏅 Rozetlerim")
        if rozetler:
            for roz in rozetler: st.markdown(f"- {roz}")
        else:
            st.caption("Henüz rozet yok — önerge yaz, rozet kazan!")

        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("📊 Nasıl Puan Kazanırsın?")
        for e in ETKINLIK_PUANLARI:
            st.markdown(f"""<div class="etkinlik-satir">
              <span>{e['etkinlik']}</span>
              <span class="puan-rozet">+{e['puan']} ⭐</span>
            </div>""", unsafe_allow_html=True)

    with sag:
        c_onergeler = db()
        k_onerge_sayisi = c_onergeler.execute(
            "SELECT COUNT(*) FROM onergeler WHERE kullanici_id=?", (kid,)).fetchone()[0]
        c_onergeler.close()
        st.markdown(f"""<div class="profil-card">
          <div style="font-size:3rem;text-align:center">👤</div>
          <div style="text-align:center;font-size:1.3rem;font-weight:800;color:#e2e8f0">
            {st.session_state.kullanici_ad}</div>
          <div style="text-align:center;color:#94a3b8;font-size:0.85rem">📍 {st.session_state.kullanici_sehir}</div>
          <hr style="border-color:rgba(255,255,255,0.1);margin:16px 0">
          <div style="display:flex;justify-content:space-around;text-align:center">
            <div><div style="font-size:1.8rem;font-weight:900;color:#63b3ed">{puan}</div>
                 <div style="color:#94a3b8;font-size:0.8rem">⭐ Puan</div></div>
            <div><div style="font-size:1.8rem;font-weight:900;color:#63b3ed">{k_onerge_sayisi}</div>
                 <div style="color:#94a3b8;font-size:0.8rem">📋 Önerge</div></div>
            <div><div style="font-size:1.8rem;font-weight:900;color:#63b3ed">{len(rozetler)}</div>
                 <div style="color:#94a3b8;font-size:0.8rem">🏅 Rozet</div></div>
          </div>
        </div>""", unsafe_allow_html=True)

        ilerleme_goster(puan)
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("🎁 Ödül Kataloğu")
        st.caption("Yeterli puanın varsa ödülü talep et!")

        c_talepler = db()
        mevcut_talepler = [r["odul_ad"] for r in
            c_talepler.execute("SELECT odul_ad FROM odul_talepleri WHERE kullanici_id=?", (kid,)).fetchall()]
        c_talepler.close()

        for o in ODULLER:
            acik = puan >= o["puan"]
            css  = "odul-kart odul-acik" if acik else "odul-kart odul-kilitli"
            st.markdown(f"""<div class="{css}">
              <span style="font-size:1.5rem">{o['emoji']}</span>
              <div style="flex:1">
                <div class="odul-ad">{o['ad']}</div>
                <div class="odul-tur">{o['aciklama']}</div>
                <div class="odul-puan">{"✅ Kazanılabilir" if acik else f"🔒 {o['puan']} puan"}</div>
              </div>
            </div>""", unsafe_allow_html=True)
            if acik:
                if o["ad"] in mevcut_talepler:
                    st.caption("✅ Talep gönderildi — yönetici onaylayacak")
                elif st.button(f"🎁 Talep Et: {o['ad']}", key=f"talep_{o['ad']}"):
                    odul_talep_ekle(kid, st.session_state.kullanici_ad, o["ad"])
                    st.success(f"Talep gönderildi! Yönetici onaylayacak.")
                    st.rerun()

# ============================================================
# TOPLULUK
# ============================================================
elif st.session_state.sayfa == "topluluk":
    st.subheader("🗳️ Topluluk Önergeleri")
    fc, sc, kc = st.columns([2,1,2])
    with fc: filtre  = st.selectbox("Sırala", ["En Çok Oy","En Yeni","Meclise Gidenler"])
    with sc: arama   = st.text_input("🔍 Ara", placeholder="Konu ara...")
    with kc:
        kat_list = ["Tümü"] + list(KATEGORILER.keys())
        kat_f = st.selectbox("📂 Kategori", kat_list)

    sira_map = {"En Çok Oy":"oy","En Yeni":"yeni","Meclise Gidenler":"meclis"}
    listele  = onergeler_getir(sira_map[filtre], kat_f if kat_f!="Tümü" else None, arama or None)

    if not listele:
        st.info("Önerge bulunamadı. 🌱")
    else:
        for o in listele:
            meclis = o["oy"] >= MECLIS_OY_ESIGI
            kat_html = f'<span class="kat-etiket">{o["kategori"]} › {o["alt_kategori"]}</span>' if o.get("kategori") else ""
            st.markdown(f"""<div class="onerge-kart">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <b>#{o['id']} — {o['baslik']}</b>
                {'<span class="meclis-badge">🏛️ Meclise Gönderildi!</span>' if meclis else ""}
              </div>
              <div style="margin:5px 0">{kat_html}</div>
              <div style="color:#94a3b8;font-size:0.82rem">👤 {o['yazar']} · 🕒 {o['tarih']}</div>
              <div style="color:#cbd5e1;font-size:0.88rem;margin-top:4px">💬 <i>"{o['ham'][:80]}..."</i></div>
              <div style="color:#94a3b8;font-size:0.82rem;margin-top:4px">{o['gerekce'][:120]}...</div>
            </div>""", unsafe_allow_html=True)

            oc, dc = st.columns([2,2])
            with oc:
                if st.button(f"👍 Destekle ({o['oy']} oy)", key=f"oy_{o['id']}"):
                    if kid:
                        basarili = oy_ver(o["id"], kid)
                        if basarili:
                            puan_guncelle(kid, 10, "Önerge oylama")
                            rozet_kontrol_ve_guncelle(kid)
                            st.rerun()
                        else:
                            st.warning("Bu önergeyi zaten oyladın!")
                    else:
                        st.warning("Oy vermek için giriş yapmalısın!")
            with dc:
                if not meclis:
                    st.caption(f"🏛️ Meclise {MECLIS_OY_ESIGI-o['oy']} oy kaldı")
                else:
                    st.success("🏛️ Gündemde!")
            if o.get("admin_yanit"):
                st.info(f"🏛️ Belediye Yanıtı: {o['admin_yanit']}")
            st.caption(f"🌿 {o['karbon']:.4f} gCO₂e · {'♻️ önbellek' if o['onbellekten'] else 'GES ✅'}")
            st.divider()

# ============================================================
# YÖNETİCİ PANELİ
# ============================================================
elif st.session_state.sayfa == "admin":
    st.markdown("""<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <span style="font-size:2rem">🏛️</span>
      <div><div style="font-size:1.2rem;font-weight:800;color:#fbbf24">Yönetici Paneli</div>
      <div style="color:#94a3b8;font-size:0.82rem">Esenler Belediyesi Gençlik ve Spor Müdürlüğü</div></div>
    </div>""", unsafe_allow_html=True)

    stats = istatistik_getir()
    a1,a2,a3,a4 = st.columns(4)
    for col,sayi,etiket in [
        (a1, stats["toplam"],       "📋 Toplam Önerge"),
        (a2, stats["bekleyen"],     "⏳ Bekleyen"),
        (a3, stats["meclis"],       "🏛️ Meclise Giden"),
        (a4, len(odul_talepleri_getir()), "🎁 Ödül Talebi"),
    ]:
        col.markdown(f"""<div class="stat-kart">
          <div class="stat-sayi">{sayi}</div>
          <div class="stat-etiket">{etiket}</div></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    at1,at2,at3,at4 = st.tabs(["📋 Önerge Yönetimi","🎁 Ödül Talepleri","⭐ Puan Dağıt","📊 İstatistikler"])

    with at1:
        onergeler = onergeler_getir("yeni")
        if not onergeler:
            st.info("Henüz önerge yok.")
        else:
            for o in onergeler:
                renk = {"beklemede":"#fbbf24","onaylandi":"#34d399","reddedildi":"#f87171"}.get(o["durum"],"#94a3b8")
                kat_html = f'<span class="kat-etiket">{o["kategori"]}</span>' if o.get("kategori") else ""
                st.markdown(f"""<div class="admin-kart">
                  <div style="display:flex;justify-content:space-between">
                    <b>#{o['id']} {o['baslik']}</b>
                    <span style="color:{renk};font-size:0.82rem;font-weight:700">{o['durum'].upper()}</span>
                  </div>
                  <div style="margin:4px 0">{kat_html}</div>
                  <div style="color:#94a3b8;font-size:0.8rem">
                    👤 {o['yazar']} · 🕒 {o['tarih']} · 👍 {o['oy']} oy
                    {"· 🏛️ MECLİSE GİDECEK" if o['oy']>=MECLIS_OY_ESIGI else ""}
                  </div>
                  <div style="color:#cbd5e1;font-size:0.85rem;margin-top:4px">"{o['ham'][:100]}..."</div>
                </div>""", unsafe_allow_html=True)
                c1,c2,c3 = st.columns([1,1,2])
                with c1:
                    if st.button("✅ Onayla", key=f"onayla_{o['id']}"):
                        onerge_guncelle(o["id"], durum="onaylandi"); st.rerun()
                with c2:
                    if st.button("❌ Reddet", key=f"reddet_{o['id']}"):
                        onerge_guncelle(o["id"], durum="reddedildi"); st.rerun()
                with c3:
                    yanit = st.text_input("Resmi yanıt", key=f"yi_{o['id']}",
                                          value=o.get("admin_yanit",""),
                                          placeholder="Belediye resmi yanıtı...")
                    if st.button("💬 Gönder", key=f"yg_{o['id']}"):
                        onerge_guncelle(o["id"], yanit=yanit)
                        st.success("Yanıt gönderildi!")
                st.divider()

    with at2:
        st.subheader("🎁 Ödül Talepleri")
        talepler = odul_talepleri_getir()
        if not talepler:
            st.info("Henüz ödül talebi yok.")
        else:
            for t in talepler:
                renk = "#34d399" if t["durum"]=="teslim edildi" else "#fbbf24"
                st.markdown(f"""<div class="admin-kart">
                  <div style="display:flex;justify-content:space-between">
                    <span>🎁 <b>{t['odul_ad']}</b></span>
                    <span style="color:{renk};font-size:0.82rem">{t['durum'].upper()}</span>
                  </div>
                  <div style="color:#94a3b8;font-size:0.8rem">
                    👤 {t['kullanici_ad']} · 🕒 {t['tarih']}</div>
                </div>""", unsafe_allow_html=True)
                if t["durum"] != "teslim edildi":
                    if st.button(f"✅ Teslim Et #{t['id']}", key=f"talep_{t['id']}"):
                        odul_talep_onayla(t["id"]); st.rerun()

    with at3:
        st.subheader("⭐ Manuel Puan Dağıt")
        c_kul = db()
        kullanicilar = c_kul.execute("SELECT id,ad,puan FROM kullanicilar ORDER BY puan DESC").fetchall()
        c_kul.close()
        if not kullanicilar:
            st.info("Henüz kayıtlı kullanıcı yok.")
        else:
            secili_kul = st.selectbox("Kullanıcı Seç", [f"{k['ad']} (ID:{k['id']}, {k['puan']} puan)" for k in kullanicilar])
            secili_id  = kullanicilar[[f"{k['ad']} (ID:{k['id']}, {k['puan']} puan)" for k in kullanicilar].index(secili_kul)]["id"]
            ek_puan = st.number_input("Eklenecek Puan", min_value=0, max_value=5000, step=10, value=50)
            sebep   = st.selectbox("Sebebi", [e["etkinlik"] for e in ETKINLIK_PUANLARI])
            if st.button("⭐ Puan Ekle", type="primary"):
                puan_guncelle(secili_id, ek_puan, sebep)
                rozet_kontrol_ve_guncelle(secili_id)
                st.success(f"+{ek_puan} puan eklendi!")

    with at4:
        st.subheader("📊 Platform İstatistikleri")
        if stats["kat_dag"]:
            st.markdown("**Kategori Dağılımı:**")
            for row in stats["kat_dag"]:
                if row["kategori"]:
                    oran = int(row["sayi"]/stats["toplam"]*100) if stats["toplam"] else 0
                    st.markdown(f"""<div class="etkinlik-satir">
                      <span>{row['kategori']}</span>
                      <span class="puan-rozet">{row['sayi']} önerge ({oran}%)</span>
                    </div>""", unsafe_allow_html=True)
        st.markdown(f"""<br><div class="bilgi-kutu">
        🌿 Toplam Karbon: <b>{stats['karbon']:.4f} gCO₂e</b><br>
        ♻️ Önbellekten: <b>{stats['onbellekten']} istek</b><br>
        🌱 Esenler GES ile nötralize: <b>%100</b>
        </div>""", unsafe_allow_html=True)
