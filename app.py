import os, re, asyncio, logging
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from cachetools import TTLCache

from providers import get_all_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="PhoneScope OSINT")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Cache for 60 minutes (3600 seconds)
cache = TTLCache(maxsize=1000, ttl=3600)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/lookup")
@limiter.limit("10/minute")
async def lookup(request: Request, number: str):
    if not number or not re.search(r"\d{6,}", number):
        raise HTTPException(400, "رقم غير صالح")
    
    # Normalize basic format
    num = re.sub(r"[^\d+]", "", number.strip())
    if not num.startswith("+"):
        num = "+" + num
        
    if num in cache:
        log.info(f"Cache hit for {num}")
        return JSONResponse(cache[num])
        
    try:
        data = await get_all_info(num)
        if "error" in data.get("basic", {}):
            raise HTTPException(400, data["basic"]["error"])
        cache[num] = data
        return JSONResponse(data)
    except Exception as e:
        log.error(f"Lookup failed: {e}")
        raise HTTPException(500, "حدث خطأ أثناء جلب البيانات")
