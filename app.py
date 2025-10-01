import streamlit as st
import asyncio
import subprocess
import sys
import os

# Install Playwright browsers on Streamlit Cloud
if not os.path.exists("/home/appuser/.cache/ms-playwright/chromium_headless_shell-1187"):
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install-deps", "chromium"], check=True)
    except Exception as e:
        print(f"Error installing Playwright: {e}")

import streamlit as st
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from threading import Thread
from threading import Thread

def scrape_page_sync(url: str, result_container):
    """Run async scraping in a separate thread"""
    async def scrape():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            page = await browser.new_page()
            await stealth_async(page)
            await page.goto(url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(10)
            html = await page.content()
            await browser.close()
            return html
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(scrape())
    loop.close()
    result_container['html'] = result

st.title("Web Page HTML Downloader (Stealth Mode)")
url = st.text_input("Enter URL:", placeholder="https://example.com")

if st.button("Get HTML"):
    if url:
        with st.spinner("Loading page... Please wait 10 seconds..."):
            try:
                result = {}
                thread = Thread(target=scrape_page_sync, args=(url, result))
                thread.start()
                thread.join()
                
                html = result['html']
                
                st.success("Page loaded successfully!")
                
                with st.expander("Preview HTML"):
                    st.code(html[:1000] + "...", language="html")
                
                st.download_button(
                    label="Download HTML",
                    data=html,
                    file_name="page_source.html",
                    mime="text/html"
                )
            except Exception as e:
                st.error(f"Error: {str(e)}")
    else:
        st.warning("Please enter a URL")

