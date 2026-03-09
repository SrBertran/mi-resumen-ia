import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser
from dateutil import parser as dtparser
from unidecode import unidecode


# --- Config ---
FEEDS = [
    # General tech / AI
    ("TechCrunch", "https://techcrunch.com/tag/artificial-intelligence/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("VentureBeat", "https://venturebeat.com/category/ai/feed/"),
    ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss"),

    # Official sources
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Anthropic", "https://www.anthropic.com/news/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Meta AI", "https://ai.meta.com/blog/rss/"),

    # Dev / research-ish
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),

    # ES
    ("Xataka", "https://www.xataka.com/tag/inteligencia-artificial/rss2.xml"),
    ("Hipertextual", "https://hipertextual.com/tag/inteligencia-artificial/feed"),
]

LOOKBACK_HOURS = 48  # últimas 48h
MAX_ITEMS_TOTAL = 60
TOP_N = 5


# --- Helpers ---
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_url(url: str) -> str:
    """
    Remove common tracking params and normalize.
    """
    try:
        p = urlparse(url)
        qs = [(k, v) for (k, v) in parse_qsl(p.query, keep_blank_values=True)
              if not (k.lower().startswith("utm_") or k.lower() in {"ref", "ref_src", "fbclid", "gclid"})]
        new_query = urlencode(qs, doseq=True)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))
    except Exception:
        return url


def safe_parse_date(entry) -> datetime | None:
    # feedparser sometimes provides published_parsed / updated_parsed
    for key in ("published", "updated", "created"):
        if key in entry and entry.get(key):
            try:
                return dtparser.parse(entry.get(key)).astimezone(timezone.utc)
            except Exception:
                pass
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    if getattr(entry, "updated_parsed", None):
        try:
            return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def slugify(text: str, max_words: int = 8) -> str:
    text = unidecode(text).lower()
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split(" ")[:max_words]
    return "-".join([w for w in words if w])


def source_key(source_name: str) -> str:
    s = unidecode(source_name).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    # some nicer aliases
    aliases = {
        "mittechnologyreview": "mittr",
        "ieeespectrum": "ieee",
        "theverge": "theverge",
        "venturebeat": "venturebeat",
        "techcrunch": "techcrunch",
        "huggingface": "huggingface",
        "openai": "openai",
        "anthropic": "anthropic",
        "googleai": "googleai",
        "deepmind": "deepmind",
        "metaai": "metaai",
        "xataka": "xataka",
        "hipertextual": "hipertextual",
    }
    return aliases.get(s, s[:20] or "source")


def classify(item: dict) -> tuple[str, list[str]]:
    """
    Returns (category, tags)
    """
    src = (item.get("source") or "").lower()
    url = (item.get("url") or "").lower()
    title = (item.get("title") or "").lower()

    # Official / launches
    if any(x in src for x in ["openai", "anthropic", "deepmind", "google", "meta"]) or any(
        x in url for x in ["openai.com", "anthropic.com", "deepmind.google", "blog.google", "ai.meta.com"]
    ):
        return "lanzamientos", ["producto"]

    # Regulation / policy
    if any(x in title for x in ["regulación", "regulacion", "ley", "ai act", "copyright", "demanda", "tribunal", "comisión", "commission"]):
        return "regulación", ["regulación"]

    # Research / papers
    if any(x in src for x in ["ieee", "mittr"]) or any(x in title for x in ["paper", "arxiv", "estudio", "research", "benchmark"]):
        return "investigación", ["investigación"]

    # Tools / dev
    if any(x in src for x in ["hugging face"]) or any(x in title for x in ["open source", "repositorio", "github", "sdk", "librería", "library"]):
        return "herramientas", ["herramientas"]

    # Business
    if any(x in title for x in ["ronda", "financiación", "financiacion", "acquisition", "adquiere", "compra", "startup", "inversión", "investment"]):
        return "negocio", ["negocio"]

    return "general", ["ia"]


def build_id(source: str, published_at: datetime, title: str) -> str:
    s = source_key(source)
    date = published_at.strftime("%Y-%m-%d")
    return f"{s}-{date}-{slugify(title)}"


def extract_summary(entry) -> str:
    # prefer summary/detail-ish; keep it short
    txt = entry.get("summary") or entry.get("description") or ""
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt)).strip()
    if not txt:
        return ""
    return (txt[:220] + "…") if len(txt) > 220 else txt


def main():
    cutoff = now_utc() - timedelta(hours=LOOKBACK_HOURS)

    items = []
    seen_urls = set()

    for source, feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:50]:
            url = normalize_url(entry.get("link") or "")
            if not url or url in seen_urls:
                continue

            published = safe_parse_date(entry)
            if not published:
                continue
            if published < cutoff:
                continue

            title = (entry.get("title") or "").strip()
            if not title:
                continue

            item = {
                "title": title,
                "url": url,
                "source": source,
                "published_at": published.isoformat().replace("+00:00", "Z"),
                "summary": extract_summary(entry) or "Qué pasó: (resumen pendiente)",
                "why_it_matters": "",  # lo rellenaremos más adelante con LLM
                "tags": [],
            }
            category, tags = classify(item)
            item["category"] = category
            item["tags"] = tags

            item["id"] = build_id(source, published, title)

            seen_urls.add(url)
            items.append(item)

    # Sort newest first
    items.sort(key=lambda x: x["published_at"], reverse=True)

    # Limit total
    items = items[:MAX_ITEMS_TOTAL]

    # Top N: newest N for now (later we can score)
    top = items[:TOP_N]

    # Group remaining by category into sections
    buckets = {
        "lanzamientos": "Lanzamientos",
        "negocio": "Negocio",
        "regulación": "Regulación",
        "investigación": "Investigación",
        "herramientas": "Herramientas",
        "general": "General",
    }

    rest = items[TOP_N:]
    section_items = {}
    for it in rest:
        cat = it.get("category", "general")
        section_items.setdefault(cat, []).append(it)

    sections = []
    for cat, display in buckets.items():
        if cat in section_items and section_items[cat]:
            sections.append({"name": display, "items": section_items[cat]})

    # Date for the daily file (UTC date; you can switch to Europe/Madrid later)
    out = {
        "date": now_utc().strftime("%Y-%m-%d"),
        "title": "Resumen diario de IA",
        "top": top,
        "sections": sections,
    }

    with open("data/daily.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Generated data/daily.json with {len(items)} items ({len(top)} top).")


if __name__ == "__main__":
    main()