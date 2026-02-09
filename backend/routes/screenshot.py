import base64
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
from urllib.parse import urlparse

router = APIRouter()


def normalize_url(url: str) -> str:
    """
    Normalize URL to ensure it has a proper protocol.
    If no protocol is specified, default to https://
    """
    url = url.strip()
    
    # Parse the URL
    parsed = urlparse(url)
    
    # Check if we have a scheme
    if not parsed.scheme:
        # No scheme, add https://
        url = f"https://{url}"
    elif parsed.scheme in ['http', 'https']:
        # Valid scheme, keep as is
        pass
    else:
        # Check if this might be a domain with port (like example.com:8080)
        # urlparse treats this as scheme:netloc, but we want to handle it as domain:port
        if ':' in url and not url.startswith(('http://', 'https://', 'ftp://', 'file://')):
            # Likely a domain:port without protocol
            url = f"https://{url}"
        else:
            # Invalid protocol
            raise ValueError(f"Unsupported protocol: {parsed.scheme}")
    
    return url


def bytes_to_data_url(image_bytes: bytes, mime_type: str) -> str:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{base64_image}"


async def capture_screenshot(
    target_url: str, api_key: str, device: str = "desktop"
) -> bytes:
    api_base_url = "https://api.screenshotone.com/take"

    params = {
        "access_key": api_key,
        "url": target_url,
        "full_page": "true",
        "device_scale_factor": "1",
        "format": "png",
        "block_ads": "true",
        "block_cookie_banners": "true",
        "block_trackers": "true",
        "cache": "false",
        "viewport_width": "342",
        "viewport_height": "684",
    }

    if device == "desktop":
        params["viewport_width"] = "1280"
        params["viewport_height"] = "832"

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(api_base_url, params=params)
        if response.status_code == 200 and response.content:
            return response.content
        else:
            raise Exception("Error taking screenshot")


class ScreenshotRequest(BaseModel):
    url: str
    apiKey: str


class ScreenshotResponse(BaseModel):
    url: str


class ScrapeUrlRequest(BaseModel):
    url: str


class ScrapeUrlResponse(BaseModel):
    content: str


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def clean_scraped_html(html: str) -> str:
    """Remove common debug/template artifacts from scraped HTML."""
    html = re.sub(r'"\s*==\s*\$\d+', '"', html)
    html = re.sub(r'\s*==\s*\$\d+', '', html)
    return html


@router.post("/api/scrape-url", response_model=ScrapeUrlResponse)
async def scrape_url(request: ScrapeUrlRequest):
    """
    Scrape the full HTML document from the given URL.
    Returns the complete page HTML (response body) for later use (e.g. import into editor).
    Uses a browser User-Agent; for JS-rendered content a headless browser would be needed.
    """
    try:
        normalized_url = normalize_url(request.url.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": BROWSER_USER_AGENT},
        ) as client:
            response = await client.get(normalized_url)
            response.raise_for_status()
            html = response.text
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch URL: {e.response.status_code} {e.response.reason_phrase}",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Request error: {str(e)}. Check that the URL is reachable.",
        )

    html = clean_scraped_html(html)
    return ScrapeUrlResponse(content=html)


@router.post("/api/screenshot")
async def app_screenshot(request: ScreenshotRequest):
    # Extract the URL from the request body
    url = request.url
    api_key = request.apiKey

    try:
        # Normalize the URL
        normalized_url = normalize_url(url)
        
        # Capture screenshot with normalized URL
        image_bytes = await capture_screenshot(normalized_url, api_key=api_key)

        # Convert the image bytes to a data url
        data_url = bytes_to_data_url(image_bytes, "image/png")

        return ScreenshotResponse(url=data_url)
    except ValueError as e:
        # Handle URL normalization errors
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        # Handle other errors
        raise HTTPException(status_code=500, detail=f"Error capturing screenshot: {str(e)}")
