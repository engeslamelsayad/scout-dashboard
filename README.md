# Scout Dashboard

واجهة إدارة لـ Scout Agent — منصة متابعة إعلانات المنافسين في MENA.

> ريبو مستقل يتشارك نفس الـ Railway Postgres مع Scout Agent.

## التبويبات

| التبويب | الوظيفة |
|---------|---------|
| 📊 نظرة عامة | إحصائيات + سجل الـ runs + تشغيل يدوي |
| 🔍 Search Terms | إضافة/حذف كلمات البحث مع التحكم في التكلفة |
| 🏢 المنافسين | Page IDs + نشاط هذا الأسبوع مقارنة بالماضي |
| 🌍 الدول | الدول المراقبة + TikTok + عتبة الثقة |
| 🏪 المتجر | سياق البراند (بيتحقن في تفكير الـ Scout) |
| 🏆 Winners | إعلانات شغّالة +14 يوم مع روابط مباشرة |
| 📈 الثيمات | تاريخ الثيمات المكتشفة عبر كل الـ runs |
| 🗂 Swipe File | حفظ إعلانات مع ملاحظات وتاجات |
| ⚙️ الإعدادات | إعدادات التنبيهات + اختبار تيليجرام |

## الـ Deploy على Railway

### 1. إنشاء Service جديد
Railway ← مشروعك (نفس project الـ Scout) ← **New Service** ← **GitHub Repo** ← هذا الريبو

### 2. Variables (في Railway Dashboard service)

```
DATABASE_URL              = [نفس الـ Scout — private URL من Postgres service]
DASHBOARD_PASSWORD        = كلمة_سرك
SECRET_KEY                = أي_نص_عشوائي
RAILWAY_API_TOKEN         = [من Account Settings → Tokens]
RAILWAY_SCOUT_SERVICE_ID  = [من رابط Scout service في Railway]
RAILWAY_ENVIRONMENT_ID    = [من رابط الـ environment في Railway]
TELEGRAM_BOT_TOKEN        = [اختياري]
TELEGRAM_CHAT_ID          = [اختياري]
```

### إيجاد الـ Service ID والـ Environment ID

**Service ID:** افتح Scout service في Railway — الـ URL:
```
railway.app/project/PROJECT_ID/service/SERVICE_ID  ← انسخ هذا
```

**Environment ID:** اضغط على اسم الـ environment (Production/Dev):
```
railway.app/project/PROJECT_ID/environment/ENVIRONMENT_ID  ← انسخ هذا
```

### 3. Start Command
Railway بيقراه من `railway.toml` تلقائياً:
```
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2
```

## هيكل الملفات

| ملف | الدور |
|-----|-------|
| `app.py` | Flask web app + كل الـ API endpoints |
| `db_reader.py` | طبقة DB خفيفة (read + config فقط) |
| `railway_api.py` | تشغيل الـ Scout عبر Railway GraphQL API |
| `ui.html` | الـ UI الكاملة (9 تبويبات) |
| `requirements.txt` | Flask + psycopg + pgvector فقط |
| `railway.toml` | إعدادات الـ deployment |
