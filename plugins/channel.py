import re
import logging
from plugins.Dreamxfutures.Imdbposter import get_movie_details, fetch_image
from database.users_chats_db import db
from pyrogram import Client, filters, enums
from info import CHANNELS, MOVIE_UPDATE_CHANNEL, LINK_PREVIEW, ABOVE_PREVIEW
from Script import script
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


CAPTION_LANGUAGES = {
    "hin": "Hindi", "hindi": "Hindi",
    "tam": "Tamil", "tamil": "Tamil",
    "kan": "Kannada", "kannada": "Kannada",
    "tel": "Telugu", "telugu": "Telugu",
    "mal": "Malayalam", "malayalam": "Malayalam",
    "eng": "English", "english": "English",
    "pun": "Punjabi", "punjabi": "Punjabi",
    "ben": "Bengali", "bengali": "Bengali",
    "mar": "Marathi", "marathi": "Marathi",
    "guj": "Gujarati", "gujarati": "Gujarati",
    "urd": "Urdu", "urdu": "Urdu"
}

OTT_PLATFORMS = {
    "nf": "Netflix", "netflix": "Netflix",
    "sonyliv": "SonyLiv", "sony": "SonyLiv", "sliv": "SonyLiv",
    "amzn": "Amazon Prime Video", "prime": "Amazon Prime Video", "primevideo": "Amazon Prime Video",
    "hotstar": "Disney+ Hotstar", "zee5": "Zee5",
    "jio": "JioHotstar", "jhs": "JioHotstar",
    "aha": "Aha", "hbo": "HBO Max", "paramount": "Paramount+",
    "apple": "Apple TV+", "hoichoi": "Hoichoi", "sunnxt": "Sun NXT", "viki": "Viki"
}

STANDARD_GENRES = {
    'Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary',
    'Drama', 'Family', 'Fantasy', 'Film-Noir', 'History', 'Horror', 'Music',
    'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Sport', 'Thriller', 'War', 'Western'
}

QUALITIES = [
    "HDCam", "HDTC", "CamRip", "TS", "TC", "TeleSync",
    "DVDScr", "DVDRip", "PreDVD",
    "WEBRip", "WEB-DL", "TVRip", "HDTV", "WEB DL", "WebDl",
    "BluRay", "BRRip", "BDRip",
    "360p", "480p", "720p", "1080p", "2160p", "4K", "2160p", "1440p", "540p", "240p", "140p",
    "HEVC", "HDRip"
]


QUALITY_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(q) for q in QUALITIES) + r")\b",
    re.IGNORECASE
)
IGNORE_WORDS = ({"rarbg", "dub", "sub", "sample", "mkv", "aac", "combined"} |
                STANDARD_GENRES |
                set(QUALITIES) |
                set(CAPTION_LANGUAGES.keys()) |
                set(v.lower() for v in CAPTION_LANGUAGES.values()) |
                set(OTT_PLATFORMS.keys()) |
                set(v.lower() for v in OTT_PLATFORMS.values()))
MEDIA_FILTER = filters.document | filters.video | filters.audio
CLEAN_PATTERN = re.compile(
    r'@[^ \n\r\t\.,:;!?()\[\]{}<>\\/"\'=_%]+|\bwww\.[^\s\]\)]+|\([\@^]+\)|\[[\@^]+\]')
NORMALIZE_PATTERN = re.compile(r"[._\-]+|[()\[\]{}:;'–!,.?_]")
SERIES_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:s|season)0*(\d{1,2})e0*(\d{1,3})(?![A-Za-z0-9])", re.IGNORECASE)
SEASON_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:s|season)0*(\d{1,2})(?![A-Za-z0-9])", re.IGNORECASE)
EPISODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:ep|episode)0*(\d{1,3})(?![A-Za-z0-9])", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")


def clean_mentions_links(text: str) -> str:
    return CLEAN_PATTERN.sub("", text or "").strip()


def normalize(s: str) -> str:
    s = NORMALIZE_PATTERN.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def remove_ignored_words(text: str) -> str:
    return " ".join(
        word for word in text.split()
        if word.lower() not in IGNORE_WORDS
    )


def get_qualities(text: str) -> str:
    qualities = QUALITY_PATTERN.findall(text)
    return ", ".join(qualities) if qualities else "N/A"


def extract_ott_platform(text: str) -> str:
    text = text.lower()
    platforms = {plat for key, plat in OTT_PLATFORMS.items() if key in text}
    return " | ".join(platforms) if platforms else "N/A"


def extract_media_info(filename: str, caption: str):
    """Extract media metadata from filename and caption"""
    filename = clean_mentions_links(filename).title()
    caption_clean = clean_mentions_links(caption).lower() if caption else ""
    unified = f"{caption_clean} {filename.lower()}".strip()

    season = episode = year = None
    tag = "#MOVIE"
    processed_raw = base_raw = filename
    quality = get_qualities(caption_clean) or get_qualities(
        filename.lower()) or "N/A"
    ott_platform = extract_ott_platform(f"{filename} {caption_clean}")

    lang_keys = {
        k for k in CAPTION_LANGUAGES if k in caption_clean or k in filename.lower()}
    language = ", ".join(CAPTION_LANGUAGES[k]
                         for k in lang_keys) if lang_keys else "N/A"

    if series_match := SERIES_PATTERN.search(unified):
        season, episode = series_match.groups()
        season = season.lstrip("0") or "0"
        episode = episode.lstrip("0") or "0"
        match_str = series_match.group(0)
        start_idx = filename.lower().find(match_str.lower())
        end_idx = start_idx + len(match_str)
        processed_raw = filename[:end_idx]
        base_raw = filename[:start_idx]
        tag = "#SERIES"

        if year_match := YEAR_PATTERN.search(filename.lower()[end_idx:]):
            year = year_match.group(0)
            year_idx = filename.lower().find(year, end_idx)
            if year_idx != -1:
                processed_raw = filename[:year_idx + 4]
                base_raw += f" {year}"

    elif season_match := SEASON_PATTERN.search(unified):
        season = season_match.group(1).lstrip("0") or "0"
        match_str = season_match.group(0)
        start_idx = filename.lower().find(match_str.lower())
        end_idx = start_idx + len(match_str)
        processed_raw = filename[:end_idx]
        base_raw = filename[:start_idx]
        tag = "#SERIES"

        if year_match := YEAR_PATTERN.search(filename.lower()[end_idx:]):
            year = year_match.group(0)
            year_idx = filename.lower().find(year, end_idx)
            if year_idx != -1:
                base_raw = filename[:year_idx + 4]

    elif episode_match := EPISODE_PATTERN.search(unified):
        episode = episode_match.group(1).lstrip("0") or "0"
        match_str = episode_match.group(0)
        start_idx = filename.lower().find(match_str.lower())
        end_idx = start_idx + len(match_str)
        processed_raw = filename[:end_idx]
        base_raw = filename[:start_idx]
        tag = "#SERIES"

        if year_match := YEAR_PATTERN.search(filename.lower()[end_idx:]):
            year = year_match.group(0)
            year_idx = filename.lower().find(year, end_idx)
            if year_idx != -1:
                base_raw = filename[:year_idx + 4]

    else:
        if year_match := YEAR_PATTERN.search(unified):
            year = year_match.group(0)
            year_idx = filename.lower().find(year.lower())
            if year_idx != -1:
                processed_raw = filename[:year_idx + 4]
                base_raw = processed_raw
        else:
            if qual_match := QUALITY_PATTERN.search(unified):
                qual_str = qual_match.group(0)
                qual_idx = filename.lower().find(qual_str.lower())
                if qual_idx != -1:
                    processed_raw = filename[:qual_idx]
                    base_raw = processed_raw

    base_name = normalize(remove_ignored_words(base_raw))
    if year and year not in base_name:
        base_name += f" {year}"

    return {
        "processed": normalize(processed_raw),
        "base_name": base_name,
        "tag": tag,
        "season": season,
        "episode": episode,
        "year": year,
        "quality": quality,
        "ott_platform": ott_platform,
        "language": language
    }


@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):

    media = next(
        (getattr(message, ft) for ft in ("document", "video", "audio")
         if getattr(message, ft, None)),
        None
    )
    if not media:
        return

    media.file_type = next(ft for ft in (
        "document", "video", "audio") if hasattr(message, ft))
    media.caption = message.caption or ""

    if not await save_file(media):
        logger.info("Skipping update for %s", media.file_name)
        return

    try:
        if await db.movie_update_status(bot.me.id):
            await process_and_send_update(bot, media.file_name, media.caption)
        else:
            logger.debug("Movie updates disabled for bot %s", bot.me.id)
    except Exception:
        logger.exception("Error processing %s", media.file_name)


async def process_and_send_update(bot, filename, caption):

    try:
        media_info = extract_media_info(filename, caption)
        processed = media_info["processed"]

        result = await db.filename_col.update_one(
            {"_id": processed},
            {"$setOnInsert": {"_id": processed}},
            upsert=True
        )
        if not result.upserted_id:
            logger.info("Skipping duplicate: %s", processed)
            return

        details = await get_movie_details(media_info["base_name"]) or {}
        language = media_info["language"] or details.get("language") or "N/A"
        year = media_info["year"] or details.get("year")

        raw_genres = details.get("genres", [])
        if isinstance(raw_genres, str):
            raw_genres = [g.strip() for g in raw_genres.split(",")]
        genres = ", ".join(
            g for g in raw_genres if g in STANDARD_GENRES) or "N/A"

        poster_url = details.get("poster_url")
        resized_poster = None
        if poster_url and not LINK_PREVIEW:
            resized_poster = await fetch_image(poster_url)

        text = script.MOVIE_UPDATE_NOTIFY_TXT.format(
            poster_url=poster_url or "",
            imdb_url=details.get("url", ""),
            filename=processed,
            tag=media_info["tag"],
            genres=genres,
            ott=media_info["ott_platform"],
            quality=media_info["quality"],
            language=language,
            rating=details.get("rating", "N/A"),
            search_link=temp.B_LINK
        )

        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                'ɢᴇᴛ ғɪʟᴇs',
                url=f"https://t.me/{temp.U_NAME}?start=getfile-{processed.replace(' ', '-')}"
            )
        ]])

        send_params = {
            "chat_id": MOVIE_UPDATE_CHANNEL,
            "text": text,
            "reply_markup": buttons,
            "parse_mode": enums.ParseMode.HTML
        }

        if resized_poster:
            photo_params = send_params.copy()
            photo_params.pop("text")
            await bot.send_photo(photo=resized_poster, caption=text, **photo_params)
        elif poster_url and LINK_PREVIEW:
            send_params["invert_media"] = ABOVE_PREVIEW
            await bot.send_message(**send_params)
        else:
            await bot.send_message(**send_params)

    except PyMongoError as e:
        logger.error("Database error: %s", e)
    except Exception as e:
        logger.exception("Processing failed: %s", e)
