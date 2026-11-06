import os, logging, asyncio
import httpx
import phonenumbers
from phonenumbers import geocoder, carrier, timezone, number_type, PhoneNumberType

log = logging.getLogger(__name__)

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
NUMVERIFY_KEY = os.getenv("NUMVERIFY_KEY")
HIBP_KEY = os.getenv("HIBP_KEY")
DEHASHED_KEY = os.getenv("DEHASHED_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

TYPE_MAP = {
    PhoneNumberType.MOBILE: "Mobile",
    PhoneNumberType.FIXED_LINE: "Fixed line",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixed line or mobile",
    PhoneNumberType.TOLL_FREE: "Toll free",
    PhoneNumberType.PREMIUM_RATE: "Premium rate",
    PhoneNumberType.SHARED_COST: "Shared cost",
    PhoneNumberType.VOIP: "VoIP",
    PhoneNumberType.PERSONAL_NUMBER: "Personal number",
    PhoneNumberType.PAGER: "Pager",
    PhoneNumberType.UAN: "UAN",
    PhoneNumberType.VOICEMAIL: "Voicemail",
    PhoneNumberType.UNKNOWN: "Unknown",
}

def get_basic_info(num_str: str):
    try:
        pn = phonenumbers.parse(num_str, None)
    except Exception as e:
        return {"error": f"parse failed: {e}"}
    if not phonenumbers.is_valid_number(pn):
        return {"error": "رقم غير صالح — استخدم صيغة دولية"}
    return {
        "e164": phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164),
        "international": phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "national": phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.NATIONAL),
        "country_code": pn.country_code,
        "region": geocoder.description_for_number(pn, "en") or "Unknown",
        "carrier": carrier.name_for_number(pn, "en") or "Unknown",
        "type": TYPE_MAP.get(number_type(pn), "Unknown"),
        "timezones": list(timezone.time_zones_for_number(pn)),
        "is_voip": number_type(pn) == PhoneNumberType.VOIP
    }

async def fetch_numverify(client, num_str):
    if not NUMVERIFY_KEY: return {}
    try:
        r = await client.get("http://apilayer.net/api/validate", params={"access_key": NUMVERIFY_KEY, "number": num_str, "format": 1})
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        log.warning(f"Numverify failed: {e}")
        return {}

async def fetch_hibp(client, num_str):
    if not HIBP_KEY: return []
    try:
        r = await client.get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{num_str}", headers={"hibp-api-key": HIBP_KEY, "user-agent": "PhoneScope"})
        if r.status_code == 200:
            return [b.get("Name") for b in r.json()]
        return []
    except Exception as e:
        log.warning(f"HIBP failed: {e}")
        return []

async def fetch_twilio(client, num_str):
    if not TWILIO_SID or not TWILIO_TOKEN: return {}
    try:
        url = f"https://lookups.twilio.com/v2/PhoneNumbers/{num_str}?Fields=caller_name,line_type_intelligence"
        r = await client.get(url, auth=(TWILIO_SID, TWILIO_TOKEN))
        return r.json() if r.status_code == 200 else {}
    except Exception as e:
        log.warning(f"Twilio failed: {e}")
        return {}

async def fetch_dehashed(client, num_str):
    if not DEHASHED_KEY: return []
    try:
        r = await client.get("https://api.dehashed.com/search", params={"query": num_str}, auth=(os.getenv("DEHASHED_EMAIL", ""), DEHASHED_KEY), headers={"Accept": "application/json"})
        if r.status_code == 200:
            data = r.json()
            return data.get("entries", [])[:5] # Top 5
        return []
    except Exception as e:
        log.warning(f"Dehashed failed: {e}")
        return []

async def fetch_serpapi(client, num_str):
    if not SERPAPI_KEY: return []
    try:
        r = await client.get("https://serpapi.com/search", params={"q": num_str, "api_key": SERPAPI_KEY, "engine": "google", "num": 10})
        if r.status_code == 200:
            return [{"title": res.get("title"), "link": res.get("link"), "snippet": res.get("snippet")} for res in r.json().get("organic_results", [])]
        return []
    except Exception as e:
        log.warning(f"SerpAPI failed: {e}")
        return []

def get_social_links(num_str):
    from urllib.parse import quote_plus
    bare = num_str.strip("+")
    q = quote_plus(num_str)
    return {
        "Facebook": f"https://www.facebook.com/search/top?q={q}",
        "Instagram": f"https://www.instagram.com/explore/tags/{bare}/",
        "Twitter/X": f"https://twitter.com/search?q={q}",
        "TikTok": f"https://www.tiktok.com/search?q={q}",
        "WhatsApp": f"https://wa.me/{bare}",
        "Telegram": f"https://t.me/+{bare}",
        "Truecaller": f"https://www.truecaller.com/search/global/{bare}",
        "Sync.me": f"https://sync.me/search/?number={q}",
        "Google": f"https://www.google.com/search?q={q}",
        "DuckDuckGo": f"https://duckduckgo.com/?q={q}"
    }

async def get_all_info(num_str: str) -> dict:
    basic = get_basic_info(num_str)
    if "error" in basic:
        return {"basic": basic}

    results = {
        "basic": basic,
        "breaches": [],
        "dehashed": [],
        "search_results": [],
        "social_links": get_social_links(num_str),
        "risk_score": 0,
        "errors": []
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        numv, hibp, twil, deh, serp = await asyncio.gather(
            fetch_numverify(client, num_str),
            fetch_hibp(client, num_str),
            fetch_twilio(client, num_str),
            fetch_dehashed(client, num_str),
            fetch_serpapi(client, num_str)
        )

    if numv and numv.get("valid"):
        if numv.get("name"): basic["name"] = numv["name"]
        if numv.get("carrier"): basic["carrier"] = numv["carrier"]
        if numv.get("location"): basic["region"] = numv["location"]
        
    if twil and twil.get("caller_name"):
        basic["twilio_name"] = twil["caller_name"].get("caller_name")
        
    results["breaches"] = hibp
    results["dehashed"] = deh
    results["search_results"] = serp

    # Risk Score Logic
    score = 0
    if len(hibp) > 0 or len(deh) > 0:
        score += 30
    if basic.get("is_voip"):
        score += 20
    results["risk_score"] = min(score, 100)

    return results
