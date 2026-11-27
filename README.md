# Telegram Chat Exporter (`@suta_tobu`)

Экспорт полной истории чата Telegram (сообщения, ответы, пересылки, реакции и медиафайлы) в JSON, Markdown и TXT с помощью `Telethon`.

## 1. Получи API-ключи Telegram
1. Перейди на https://my.telegram.org и войди по номеру телефона.
2. Открой **API development tools** и создай приложение (любые название и short name).
3. Скопируй `App api_id` и `App api_hash`.
4. Скопируй `.env.example` в `.env` и заполни значения (либо введи их прямо в терминале при первом запуске):

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

## 2. Запуск экспорта

Весь чат `@suta_tobu` **с медиафайлами** в папку `C:\Users\novra\Desktop\suta_tobu_export`:

```powershell
.\.venv\Scripts\python.exe .\export_telegram_chat.py
```

Только текст и метаданные (быстро, без скачивания медиа):

```powershell
.\.venv\Scripts\python.exe .\export_telegram_chat.py --no-media
```

Дополнительные опции:
- `--chat @username` — указать другой чат (по умолчанию `@suta_tobu`).
- `--out "C:\Users\novra\Desktop\my_folder"` — указать свою папку вывода.
- `--max-media-mb 50` — пропускать файлы тяжелее 50 МБ.
- `--limit 200` — тестовая выгрузка первых N сообщений.

При первом запуске `Telethon` попросит номер телефона, код подтверждения из Telegram и (если включена) 2FA-пароль. Файл сессии сохранится локально (`telegram_export.session`), повторный запуск автоматически пропускает уже скачанные медиафайлы.
