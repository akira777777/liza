# Telegram Chat Exporter (`@suta_tobu`)

Экспорт полной истории чата Telegram (сообщения, ответы, пересылки, реакции и медиафайлы) в JSON, Markdown и TXT с помощью `Telethon`.

## 1. Ключи API
Файл `.env` уже заполнен твоими `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` (и добавлен в `.gitignore`).

## 2. Запуск экспорта

Весь чат `@suta_tobu` **с медиафайлами** в папку `C:\Users\novra\Desktop\suta_tobu_export`:

```powershell
uv run export_telegram_chat.py
```

Только текст и метаданные (быстро, без скачивания медиа):

```powershell
uv run export_telegram_chat.py --no-media
```

Дополнительные опции:
- `--chat @username` — указать другой чат (по умолчанию `@suta_tobu`).
- `--out "C:\Users\novra\Desktop\my_folder"` — указать свою папку вывода.
- `--max-media-mb 50` — пропускать файлы тяжелее 50 МБ.
- `--limit 200` — тестовая выгрузка первых N сообщений.

При первом запуске `Telethon` попросит номер телефона, код подтверждения из Telegram и (если включена) 2FA-пароль. Файл сессии сохранится локально (`telegram_export.session`), повторный запуск автоматически пропускает уже скачанные медиафайлы.
