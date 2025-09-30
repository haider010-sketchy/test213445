import streamlit as st
import asyncio
from pyppeteer import launch
from pyppeteer_stealth import stealth

async def scrape_page(url: str):
    browser = await launch(
        headless=True,
        args=['--no-sandbox', '--disable-setuid-sandbox']
    )
    page = await browser.newPage()
    
    # Apply stealth to avoid detection
    await stealth(page)
    
    await page.goto(url, {'waitUntil': 'networkidle2'})
    
    # Wait 10 seconds for page to fully load
    await asyncio.sleep(10)
    
    html = await page.content()
    await browser.close()
    return html

st.title("Web Page HTML Downloader (Stealth Mode)")

url = st.text_input("Enter URL:", placeholder="https://example.com")

if st.button("Get HTML"):
    if url:
        with st.spinner("Loading page... Please wait 10 seconds..."):
            try:
                html = asyncio.run(scrape_page(url))
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
