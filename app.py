import streamlit as st
import asyncio
from pydoll.browser import Chrome

async def scrape_page(url: str):
    async with Chrome() as browser:
        tab = await browser.start()
        await tab.go_to(url)
        
        # Wait 10 seconds for page to fully load
        await asyncio.sleep(10)
        
        # Get the HTML source
        html = await tab.page_source
        return html

st.title("Web Page HTML Downloader")

# User input for URL
url = st.text_input("Enter URL:", placeholder="https://example.com")

if st.button("Get HTML"):
    if url:
        with st.spinner("Loading page... Please wait 10 seconds..."):
            try:
                html = asyncio.run(scrape_page(url))
                
                # Display success message
                st.success("Page loaded successfully!")
                
                # Show preview
                with st.expander("Preview HTML"):
                    st.code(html[:1000] + "...", language="html")
                
                # Download button
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