#!/usr/bin/env python3
"""Export a full Telegram chat (messages + media) via Telethon."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    Channel,
    Chat,
    Message,
    MessageMediaContact,
    MessageMediaDocument,
    MessageMediaEmpty,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaPhoto,
    MessageMediaPoll,
    MessageMediaUnsupported,
    MessageMediaWebPage,
    MessageService,
    User,
)

DEFAULT_CHAT = "@suta_tobu"
DEFAULT_OUT_DIR = Path.home() / "Desktop" / "suta_tobu_export"
NON_DOWNLOADABLE_MEDIA = (
    MessageMediaEmpty,
    MessageMediaWebPage,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaContact,
    MessageMediaPoll,
    MessageMediaUnsupported,
)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def sanitize_filename(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not cleaned:
        cleaned = "file"
    if len(cleaned) > max_len:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 12:
            cleaned = f"{stem[: max_len - len(ext) - 1]}.{ext}"
        else:
            cleaned = cleaned[:max_len]
    return cleaned


def format_entity_name(entity: Any) -> str:
    if entity is None:
        return "Unknown"
    if isinstance(entity, User):
        full = " ".join(p for p in (entity.first_name, entity.last_name) if p)
        if full:
            return full
        if entity.username:
            return f"@{entity.username}"
        return f"User({entity.id})"
    if isinstance(entity, (Chat, Channel)):
        return entity.title or f"Chat({entity.id})"
    return str(getattr(entity, "id", "Unknown"))


def extract_reactions(msg: Message) -> list[dict[str, Any]]:
    reactions_obj = getattr(msg, "reactions", None)
    if not reactions_obj or not getattr(reactions_obj, "results", None):
        return []
    out: list[dict[str, Any]] = []
    for item in reactions_obj.results:
        reaction = getattr(item, "reaction", None)
        label = getattr(reaction, "emoticon", None) or str(
            getattr(reaction, "document_id", reaction)
        )
        out.append({"reaction": label, "count": getattr(item, "count", 1)})
    return out


def extract_media_metadata(msg: Message) -> dict[str, Any] | None:
    media = getattr(msg, "media", None)
    if media is None or isinstance(media, MessageMediaEmpty):
        return None

    info: dict[str, Any] = {
        "type": type(media).__name__,
        "downloadable": not isinstance(media, NON_DOWNLOADABLE_MEDIA),
        "filename": None,
        "mime_type": None,
        "size_bytes": None,
        "local_path": None,
        "skipped_reason": None,
        "error": None,
    }

    if isinstance(media, MessageMediaPhoto):
        info["mime_type"] = "image/jpeg"
        if getattr(msg, "file", None):
            info["size_bytes"] = msg.file.size
            info["filename"] = msg.file.name or f"photo_{msg.id}.jpg"
    elif isinstance(media, MessageMediaDocument):
        file_obj = getattr(msg, "file", None)
        if file_obj:
            info["mime_type"] = file_obj.mime_type
            info["size_bytes"] = file_obj.size
            ext = file_obj.ext or ""
            info["filename"] = file_obj.name or f"doc_{msg.id}{ext}"
    elif isinstance(media, MessageMediaWebPage):
        wp = getattr(media, "webpage", None)
        info["url"] = getattr(wp, "url", None)
        info["title"] = getattr(wp, "title", None)
    elif isinstance(media, MessageMediaPoll):
        poll = getattr(media, "poll", None)
        question = getattr(poll, "question", None)
        info["question"] = getattr(question, "text", str(question)) if question else None
    elif isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
        geo = getattr(media, "geo", None)
        if geo is not None:
            info["lat"] = getattr(geo, "lat", None)
            info["long"] = getattr(geo, "long", None)
    elif isinstance(media, MessageMediaContact):
        info["phone_number"] = getattr(media, "phone_number", None)
        info["first_name"] = getattr(media, "first_name", None)
        info["last_name"] = getattr(media, "last_name", None)

    return info


async def download_message_media(
    client: TelegramClient,
    msg: Message,
    media_dir: Path,
    media_info: dict[str, Any],
    max_media_mb: float,
) -> None:
    if not media_info.get("downloadable"):
        return

    size_bytes = media_info.get("size_bytes")
    if max_media_mb > 0 and size_bytes and size_bytes > max_media_mb * 1024 * 1024:
        media_info["skipped_reason"] = f"exceeds --max-media-mb ({max_media_mb} MB)"
        return

    prefix = f"{msg.id:07d}_"
    existing = list(media_dir.glob(f"{prefix}*"))
    if existing:
        media_info["local_path"] = f"media/{existing[0].name}"
        return

    raw_name = media_info.get("filename") or f"media_{msg.id}"
    target_path = media_dir / f"{prefix}{sanitize_filename(raw_name)}"

    while True:
        try:
            saved = await client.download_media(msg, file=str(target_path))
            if saved:
                saved_path = Path(saved)
                media_info["local_path"] = f"media/{saved_path.name}"
            else:
                media_info["skipped_reason"] = "empty_download"
            return
        except FloodWaitError as exc:
            wait_s = exc.seconds + 1
            print(f"[FloodWait] Sleeping {wait_s}s while downloading media for msg {msg.id}...")
            await asyncio.sleep(wait_s)
        except Exception as exc:  # noqa: BLE001
            media_info["error"] = f"{type(exc).__name__}: {exc}"
            return


def write_outputs(
    out_dir: Path,
    chat_meta: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    payload = {
        "chat": chat_meta,
        "stats": {
            "total_messages": len(records),
            "downloaded_media": sum(
                1 for r in records if r.get("media") and r["media"].get("local_path")
            ),
            "media_errors": sum(
                1 for r in records if r.get("media") and r["media"].get("error")
            ),
        },
        "messages": records,
    }

    # Atomic JSON write via temporary file
    json_tmp = out_dir / "messages.json.tmp"
    json_final = out_dir / "messages.json"
    json_tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    json_tmp.replace(json_final)

    # Markdown transcript
    md_lines: list[str] = [
        f"# Telegram Chat Export: {chat_meta['display_name']}",
        "",
        f"- **Target**: `{chat_meta['requested_chat']}`",
        f"- **Chat ID**: `{chat_meta['id']}`",
        f"- **Username**: `{chat_meta.get('username') or '—'}`",
        f"- **Exported At (UTC)**: `{chat_meta['exported_at']}`",
        f"- **Messages**: {len(records)}",
        "",
    ]

    txt_lines: list[str] = [
        f"Telegram Chat Export: {chat_meta['display_name']} ({chat_meta['requested_chat']})",
        f"Exported At (UTC): {chat_meta['exported_at']} | Messages: {len(records)}",
        "=" * 72,
        "",
    ]

    current_day: str | None = None
    for rec in records:
        dt_str = rec.get("date") or ""
        day = dt_str[:10] if len(dt_str) >= 10 else "Unknown Date"
        time_part = dt_str[11:19] if len(dt_str) >= 19 else dt_str
        sender = rec.get("sender_name") or "Unknown"
        msg_id = rec["id"]

        if day != current_day:
            current_day = day
            md_lines.extend(["", f"## {day}", ""])

        header = f"**{sender}** (`{time_part}`, `#{msg_id}`)"
        if rec.get("reply_to_msg_id"):
            header += f" ↩ reply to `#{rec['reply_to_msg_id']}`"
        if rec.get("forwarded_from"):
            fwd = rec["forwarded_from"]
            fwd_label = fwd.get("from_name") or fwd.get("from_id") or "unknown"
            header += f" ↪ forwarded from `{fwd_label}`"
        if rec.get("edit_date"):
            header += " *(edited)*"

        md_lines.append(f"- {header}")

        if rec.get("service_action"):
            md_lines.append(f"  - *Service event: `{rec['service_action']}`*")

        text = rec.get("text") or ""
        if text:
            indented = "\n".join(f"  > {line}" for line in text.splitlines())
            md_lines.append(indented)

        media = rec.get("media")
        if media:
            local_path = media.get("local_path")
            if local_path:
                ext = Path(local_path).suffix.lower()
                if ext in IMAGE_EXTS:
                    md_lines.append(f"  - ![{Path(local_path).name}]({local_path})")
                else:
                    md_lines.append(
                        f"  - Attachment ({media['type']}): [{Path(local_path).name}]({local_path})"
                    )
            elif media.get("url"):
                md_lines.append(f"  - Link: {media['url']}")
            elif media.get("skipped_reason"):
                md_lines.append(
                    f"  - Media ({media['type']}) skipped: `{media['skipped_reason']}`"
                )
            elif media.get("error"):
                md_lines.append(f"  - Media ({media['type']}) error: `{media['error']}`")
            else:
                md_lines.append(f"  - Media: `{media['type']}`")

        reactions = rec.get("reactions") or []
        if reactions:
            r_str = " ".join(f"{r['reaction']}×{r['count']}" for r in reactions)
            md_lines.append(f"  - Reactions: {r_str}")

        # Plain-text line
        txt_prefix = f"[{dt_str}] #{msg_id} {sender}"
        if rec.get("reply_to_msg_id"):
            txt_prefix += f" (reply #{rec['reply_to_msg_id']})"
        txt_body = text
        if media and media.get("local_path"):
            txt_body = f"{txt_body}\n[MEDIA: {media['local_path']}]".strip()
        elif rec.get("service_action"):
            txt_body = f"[SERVICE: {rec['service_action']}]"
        txt_lines.append(f"{txt_prefix}: {txt_body}")

    (out_dir / "chat.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    (out_dir / "chat.txt").write_text("\n".join(txt_lines) + "\n", encoding="utf-8")


def resolve_credentials(env_file: Path) -> tuple[int, str]:
    load_dotenv(env_file)
    api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if not api_id_raw:
        print("TELEGRAM_API_ID is not set. Get API credentials at https://my.telegram.org")
        api_id_raw = input("Enter TELEGRAM_API_ID: ").strip()
    if not api_hash:
        api_hash = input("Enter TELEGRAM_API_HASH: ").strip()

    if not api_id_raw.isdigit() or not api_hash:
        raise ValueError("Invalid TELEGRAM_API_ID (must be integer) or empty TELEGRAM_API_HASH.")

    if not env_file.exists():
        save = input(f"Save credentials to {env_file}? [y/N]: ").strip().lower()
        if save in {"y", "yes", "д", "да"}:
            env_file.write_text(
                f"TELEGRAM_API_ID={api_id_raw}\nTELEGRAM_API_HASH={api_hash}\n",
                encoding="utf-8",
            )
            print(f"Saved credentials to {env_file}")

    return int(api_id_raw), api_hash


async def export_chat(args: argparse.Namespace) -> None:
    script_dir = Path(__file__).resolve().parent
    env_file = script_dir / ".env"
    api_id, api_hash = resolve_credentials(env_file)

    out_dir = Path(args.out).expanduser().resolve()
    media_dir = out_dir / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_media:
        media_dir.mkdir(parents=True, exist_ok=True)

    session_path = Path(args.session).expanduser().resolve()
    client = TelegramClient(str(session_path), api_id, api_hash)

    await client.start()
    try:
        target: str | int = args.chat.strip()
        if target.lstrip("-").isdigit():
            target = int(target)

        print(f"Resolving chat entity: {target} ...")
        entity = await client.get_entity(target)
        display_name = format_entity_name(entity)
        chat_meta = {
            "requested_chat": args.chat,
            "id": entity.id,
            "type": type(entity).__name__,
            "display_name": display_name,
            "username": getattr(entity, "username", None),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "include_media": not args.no_media,
        }
        print(f"Exporting chat '{display_name}' (ID: {entity.id}) -> {out_dir}")

        sender_cache: dict[int, tuple[str, str | None]] = {}
        records: list[dict[str, Any]] = []
        limit = args.limit if args.limit and args.limit > 0 else None

        async def get_sender_info(msg: Message) -> tuple[str, str | None]:
            sid = msg.sender_id
            if sid is None:
                return ("Unknown", None)
            if sid in sender_cache:
                return sender_cache[sid]
            sender = await msg.get_sender()
            name = format_entity_name(sender)
            username = getattr(sender, "username", None)
            sender_cache[sid] = (name, username)
            return name, username

        count = 0
        it = client.iter_messages(entity, reverse=True, limit=limit)
        while True:
            try:
                msg = await anext(it)
            except StopAsyncIteration:
                break
            except FloodWaitError as exc:
                wait_s = exc.seconds + 1
                print(f"[FloodWait] Sleeping {wait_s}s while fetching messages...")
                await asyncio.sleep(wait_s)
                continue

            sender_name, sender_username = await get_sender_info(msg)
            fwd_info = None
            if getattr(msg, "fwd_from", None):
                fwd = msg.fwd_from
                fwd_info = {
                    "from_name": getattr(fwd, "from_name", None),
                    "from_id": str(getattr(fwd, "from_id", None))
                    if getattr(fwd, "from_id", None)
                    else None,
                    "date": fwd.date.isoformat() if getattr(fwd, "date", None) else None,
                }

            media_info = extract_media_metadata(msg)
            if media_info and not args.no_media:
                await download_message_media(
                    client=client,
                    msg=msg,
                    media_dir=media_dir,
                    media_info=media_info,
                    max_media_mb=args.max_media_mb,
                )

            rec: dict[str, Any] = {
                "id": msg.id,
                "date": msg.date.isoformat() if msg.date else None,
                "edit_date": msg.edit_date.isoformat()
                if getattr(msg, "edit_date", None)
                else None,
                "sender_id": msg.sender_id,
                "sender_name": sender_name,
                "sender_username": sender_username,
                "out": bool(getattr(msg, "out", False)),
                "reply_to_msg_id": getattr(msg, "reply_to_msg_id", None),
                "forwarded_from": fwd_info,
                "service_action": type(msg.action).__name__
                if isinstance(msg, MessageService) and getattr(msg, "action", None)
                else None,
                "text": getattr(msg, "raw_text", None) or "",
                "reactions": extract_reactions(msg),
                "media": media_info,
            }
            records.append(rec)
            count += 1

            if count % 100 == 0:
                print(f"Processed {count} messages...")
            if args.checkpoint_every > 0 and count % args.checkpoint_every == 0:
                write_outputs(out_dir, chat_meta, records)
                print(f"[Checkpoint] Saved {count} messages to {out_dir}")

        write_outputs(out_dir, chat_meta, records)
        print(
            f"Done! Exported {len(records)} messages to:\n"
            f"  - {out_dir / 'messages.json'}\n"
            f"  - {out_dir / 'chat.md'}\n"
            f"  - {out_dir / 'chat.txt'}"
        )
    finally:
        await client.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a full Telegram chat (messages + media) via Telethon."
    )
    parser.add_argument(
        "--chat",
        default=DEFAULT_CHAT,
        help=f"Target username, phone, or numeric chat ID (default: {DEFAULT_CHAT})",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--session",
        default=str(Path(__file__).resolve().parent / "telegram_export"),
        help="Path prefix for the Telethon session file",
    )
    parser.add_argument(
        "--no-media",
        action="store_true",
        help="Export text & metadata only without downloading media files",
    )
    parser.add_argument(
        "--max-media-mb",
        type=float,
        default=0.0,
        help="Skip media files larger than this size in MB (0 = unlimited)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of messages to export (0 = all messages)",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=500,
        help="Save progress every N messages (default: 500)",
    )
    return parser.parse_args()


def main() -> None:
    configure_console_encoding()
    args = parse_args()
    asyncio.run(export_chat(args))


if __name__ == "__main__":
    main()
