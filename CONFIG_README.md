# Konfigurációs útmutató (Copytrader)

Ez a dokumentum bemutatja a Copytrader rendszer fő konfigurációs fájljait, azok szerkezetét, kötelező és opcionális mezőit, valamint példákat is tartalmaz.

## 1. .env (globális környezeti változók)

```
TELEGRAM_TOKEN=123456:ABC-DEF...
ALLOWED_CHAT_IDS=123456789,987654321
API_KEY=bybit_xxx...
API_BASE_URL=https://api.bybit.com
MAX_POSITION_SIZE=1.0
MAX_DRAWDOWN=0.1
RISK_PERCENTAGE=0.02
```
- **Kötelező:** TELEGRAM_TOKEN, ALLOWED_CHAT_IDS, API_KEY
- **Opcionális:** API_BASE_URL, MAX_POSITION_SIZE, MAX_DRAWDOWN, RISK_PERCENTAGE

## 2. data/users/<nickname>/config.ini (felhasználói szintű beállítások)

```
[api]
api_key = bybit_xxx...
api_secret = yyy...
url = https://api.bybit.com
is_demo = false

[telegram]
bot_token = 123456:ABC-DEF...
chat_id = 123456789

[account_modes]
mode = Hedge

[settings]
startdate = 2024-01-01
logrotationbackupcount = 14
loopintervalseconds = 120
symbolstocopy = BTCUSDT, ETHUSDT
loglevel_main = INFO
loglevel_bot = WARNING
clearlogonstartup = true
copy_multiplier = 10.0
qty_precision = 4
sl_loss_tiers_usd = 10, 20, 30
```
- **Kötelező szekciók:** [api], [settings]
- **Opcionális szekciók:** [telegram], [account_modes]
- **Kötelező mezők:** api_key, api_secret, copy_multiplier (ha nincs, alapértelmezett: 10.0)
- **Opcionális mezők:** symbolstocopy, sl_loss_tiers_usd, stb.

## 3. data/users.json (felhasználók listája)

```
{
  "users": [
    {
      "nickname": "norbi",
      "telegram_id": 123456789,
      "role": "admin",
      "account_type": "master"
    },
    {
      "nickname": "user1",
      "telegram_id": 987654321,
      "role": "user",
      "account_type": "user"
    }
  ]
}
```
- **Kötelező mezők minden usernél:** nickname, telegram_id, role, account_type
- **role:** lehet "admin" vagy "user"
- **account_type:** lehet "master" vagy "user"

## 4. Hibakezelés
- Minden hiányzó vagy hibás konfiguráció admin értesítést generál.
- A logokban és az admin üzenetekben magyar, informatív visszajelzés jelenik meg.

---

Ha kérdésed van a konfigurációval kapcsolatban, keresd az adminisztrátort vagy nézd meg a logokat/admin értesítéseket! 