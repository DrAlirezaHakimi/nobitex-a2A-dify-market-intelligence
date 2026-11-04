# مرجع API — سرویس Nobitex A2A

نشانی محلی API به‌صورت پیش‌فرض:

`http://127.0.0.1:8000`

برای مسیرهای محافظت‌شده، هدر زیر الزامی است:

```http
X-API-Key: <API_KEY>
```

مقدار `API_KEY` از فایل محلی `.env` خوانده می‌شود. این مقدار را در کد مرورگر، مخزن عمومی یا پیام‌های چت قرار ندهید.

## مسیرهای اصلی

| Method | Path | احراز هویت | توضیح |
|---|---|---|---|
| GET | `/` | خیر | اطلاعات سرویس و اعلام غیرفعال بودن اجرای معامله |
| GET | `/health` | خیر | سلامت سرویس، حالت داده و فهرست عامل‌ها |
| GET | `/.well-known/agent-card.json` | خیر | کارت هماهنگ‌ساز |
| GET | `/.well-known/agent.json` | خیر | مسیر جایگزین کارت هماهنگ‌ساز |
| GET | `/a2a/{agent}/.well-known/agent-card.json` | خیر | کارت عامل مشخص |
| POST | `/a2a/{agent}` | بله | پیام JSON-RPC عامل |
| GET | `/api/scan` | بله | غربال و تحلیل بازار |
| POST | `/api/paper/preview` | بله | محاسبه نمونه کاغذی؛ بدون ثبت سفارش |

عامل‌های مجاز: `orderflow`، `trend`، `liquidity`، `risk` و `decision`.

## GET /api/scan

پارامترهای Query:

- `top_k`: تعداد فرصت‌های خروجی؛ ۱ تا ۱۰۰، پیش‌فرض ۱۲.
- `budget_irt`: بودجه فرضی برای نمادهای IRT.
- `budget_usdt`: بودجه فرضی برای نمادهای USDT.
- `fee_bps`: کارمزد فرضی هر سمت، بر حسب basis point.

نمونه:

```bash
curl -H "X-API-Key: YOUR_LOCAL_API_KEY" "http://127.0.0.1:8000/api/scan?top_k=10"
```

فیلدهای مهم پاسخ:

- `mode`: یکی از `demo` یا `live`.
- `data_status`: توضیح منبع داده.
- `generated_at`: زمان تولید خروجی.
- `execution_enabled`: همیشه `false`.
- `metrics`: شمار نمادهای خام، غربال‌شده، حذف‌شده و تحلیل‌شده.
- `best_buy` و `best_sell`: بهترین سناریوهای مجاز در رتبه‌بندی ابتکاری.
- `opportunities`: فهرست فرصت‌های رتبه‌بندی‌شده.
- `method`: توضیح روش و محدودیت‌ها.

## POST /api/paper/preview

بدنه نمونه:

```json
{
  "symbol": "BTCIRT",
  "side": "BUY",
  "capital_quote": 50000000,
  "fee_bps_per_side": 30,
  "stop_distance_pct": 2.0,
  "risk_fraction": 0.005
}
```

این مسیر فقط یک پیش‌نمایش کاغذی و محدودیت اندازه فرضی برمی‌گرداند. هیچ سفارشی ثبت نمی‌شود. برای `SELL` وجود دارایی اسپات از قبل لازم است.

## A2A JSON-RPC

نمونه درخواست `message/send`:

```json
{
  "jsonrpc": "2.0",
  "id": "request-1",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "messageId": "message-1",
      "parts": [
        {"kind": "data", "data": {"market": {"symbol": "BTCIRT"}}}
      ]
    }
  }
}
```

این نمونه فقط شکل کلی پیام را نشان می‌دهد؛ هر عامل به ساختار داده متناسب با نقش خود نیاز دارد. روش‌های پشتیبانی‌شده در این زیرمجموعه `message/send` و `tasks/get` هستند.

## مسیرهای داشبورد محلی

این مسیرها روی سرویس خصوصی پورت 8001 هستند و برای فراخوانی عمومی طراحی نشده‌اند:

- `GET /api/ui/status`
- `POST /api/ui/scan`
- `POST /api/ui/dify`
- `GET /api/ui/history`

داشبورد فقط باید از `127.0.0.1:8001` باز شود. این پورت را با تونل عمومی در معرض اینترنت قرار ندهید.

## اتصال Dify

در HTTP Request node ورک‌فلو:

- URL: `{{#start.backend_url#}}/api/scan?top_k={{#start.top_k#}}`
- Header: `X-API-Key`
- مقدار Header: متغیر محرمانه `A2A_API_KEY` از بخش Environment Variables در Dify.

کلید `DIFY_API_KEY` چیز دیگری است: این کلید برای فراخوانی Dify Workflow از داشبورد محلی استفاده می‌شود و در `.env` با همین نام قرار می‌گیرد.
