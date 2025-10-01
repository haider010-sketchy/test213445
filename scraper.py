import sys
import os
import requests
import re
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import statistics
import traceback
import io
import pandas as pd

# Google Gemini API imports
from google import genai
from google.genai import types

# Playwright for web scraping
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
import asyncio

class AuctionScraper:
    def __init__(self, gemini_api_keys, ui_placeholders):
        self.running = True
        self._is_running = True
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.products = []
        self.percentages = []
        self.ui = ui_placeholders
        self.gemini_api_keys = [key for key in gemini_api_keys if key]
        self.current_api_key_index = 0
        self.gemini_client = None
        
        # Playwright browser instances
        self.playwright = None
        self.browser = None
        self.page = None
        self.loop = None
        
        # Rate limiting variables
        self.request_times = []
        self.max_requests_per_minute = 10
        
        if self.gemini_api_keys:
            self.setup_gemini()

    def stop(self):
        print("🛑 Stop signal received. Shutting down scraper.")
        self.running = False
        self._is_running = False
        if self.browser:
            try:
                self.loop.run_until_complete(self.browser.close())
                self.loop.run_until_complete(self.playwright.stop())
                print("   -> Playwright browser closed successfully.")
            except Exception as e:
                print(f"   -> NOTE: Harmless error during browser shutdown: {e}")
                pass

    def setup_gemini(self):
        try:
            if not self.gemini_api_keys:
                print("⚠️ No Gemini API keys found. AI price lookup will be disabled.")
                self.ui['status'].warning("No Gemini API keys found.")
                return

            api_key = self.gemini_api_keys[self.current_api_key_index]
            self.gemini_client = genai.Client(api_key=api_key)
            print(f"🤖 Gemini AI client setup with API Key #{self.current_api_key_index + 1}")
            self.ui['status'].info(f"AI price lookup enabled with Gemini Client (API Key {self.current_api_key_index + 1})")

        except Exception as e:
            print(f"🔥 FATAL ERROR setting up Gemini AI: {e}.")
            traceback.print_exc()
            self.ui['status'].error(f"An unexpected error occurred setting up Gemini AI: {e}.")
            self.gemini_client = None

    def can_make_request(self):
        """Check if we can make a request without hitting rate limits"""
        now = datetime.now()
        self.request_times = [req_time for req_time in self.request_times if now - req_time < timedelta(minutes=1)]
        return len(self.request_times) < self.max_requests_per_minute

    def wait_for_rate_limit(self):
        """Wait until we can make another request"""
        while not self.can_make_request():
            if self.request_times:
                oldest_request = min(self.request_times)
                wait_time = 60 - (datetime.now() - oldest_request).total_seconds()
                if wait_time > 0:
                    wait_message = f"Rate limit reached. Waiting {wait_time:.0f} seconds..."
                    print(f"   -> {wait_message}")
                    self.ui['status'].info(wait_message)
                    time.sleep(max(1, wait_time))
            else:
                break

    def record_request(self):
        """Record that we made a request"""
        self.request_times.append(datetime.now())

    def get_retail_price(self, product_name, image_url):
        if not self.gemini_client:
            return None
            
        for attempt in range(len(self.gemini_api_keys)):
            try:
                self.wait_for_rate_limit()
                print(f"  [AI Request] For '{product_name[:40]}...'")
                
                response = requests.get(image_url, headers=self.headers, stream=True, timeout=15)
                if response.status_code != 200:
                    print(f"     -> 🔥 FAILED to download image: {image_url} (Status: {response.status_code})")
                    return None
                
                image_bytes = response.content
                
                prompt_text = f"""
                **Task**: Find the retail price and a direct product link for the item in the image, described as '{product_name}'.
                **Output Format**: You MUST reply ONLY in the format: `PRICE, URL`. Example: `199.99, https://www.amazon.com/product`.
                **Rules**:
                1. If you cannot find the exact item, find the CLOSEST SIMILAR item from a major retailer (Amazon, Walmart, etc.). NEVER return "NONE" or "Not Found".
                2. The price must be a number only (e.g., `123.45`). No currency symbols.
                3. The URL must be a direct retail link, not an auction site.
                Your entire response must be just the price and the link, separated by a comma.
                """
                
                contents = [
                    {"role": "user", "parts": [{"text": prompt_text}, {"inline_data": {"mime_type": "image/png", "data": image_bytes}}]}
                ]
                
                self.record_request()
                
                response = self.gemini_client.models.generate_content(model="gemini-1.5-flash", contents=contents)

                response_text = response.text.strip()
                match = re.search(r'([\d,]+\.?\d*)\s*,\s*(https?://\S+)', response_text)
                if match:
                    price = match.group(1).replace(',', '')
                    link = match.group(2)
                    print(f"     -> ✅ AI Success: Found price ${price}")
                    return f"{price}, {link}"
                else:
                    print(f"     -> ⚠️ AI response format invalid: '{response_text}'")
                    raise ValueError("Invalid AI response format")

            except Exception as e:
                error_str = str(e)
                print(f"\n--- 🔥 GEMINI API ERROR on attempt {attempt + 1} ---")
                traceback.print_exc()
                print("---------------------------------\n")
                
                if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
                    wait_msg = "Rate limit hit! Waiting 30 seconds before retry..."
                    print(f"     -> {wait_msg}")
                    self.ui['status'].warning(wait_msg)
                    time.sleep(30)
                
                self.current_api_key_index = (self.current_api_key_index + 1) % len(self.gemini_api_keys)
                key_switch_msg = f"Switching to Gemini API Key #{self.current_api_key_index + 1} due to error."
                print(f"     -> {key_switch_msg}")
                self.ui['status'].warning(key_switch_msg)
                self.setup_gemini()
                self.request_times = []
        
        final_error_msg = "All Gemini API keys failed. Disabling AI for this session."
        print(f"🔥🔥 {final_error_msg}")
        self.ui['status'].error(final_error_msg)
        self.gemini_client = None
        return None

    def run(self, site, url, start_page, end_page):
        print(f"\n🚀🚀🚀 Starting scraper for site: {site} 🚀🚀🚀")
        print(f"URL: {url} | Pages: {start_page} to {end_page if end_page > 0 else 'last'}")
        
        try:
            selenium_sites = ["HiBid", "BiddingKings", "BidLlama", "MAC.bid", "Vista", "BidAuctionDepot", "BidSoflo"]
            
            if site in selenium_sites:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                
                async def init_browser():
                    print("   -> Initializing Playwright browser...")
                    self.playwright = await async_playwright().start()
                    self.browser = await self.playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
                    )
                    self.page = await self.browser.new_page()
                    await stealth_async(self.page)
                    print("   -> Browser initialized successfully.")
                
                self.loop.run_until_complete(init_browser())
            
            # Site router
            site_map = {
                "HiBid": self.scrape_hibid,
                "BiddingKings": self.scrape_biddingkings,
                "BidLlama": self.scrape_bidllama,
                "Nellis": self.scrape_nellis,
                "BidFTA": self.scrape_bidfta,
                "MAC.bid": self.scrape_macbid,
                "A-Stock": self.scrape_astock,
                "702Auctions": self.scrape_702auctions,
                "Vista": self.scrape_vista,
                "BidSoflo": self.scrape_bidsoflo,
                "BidAuctionDepot": self.scrape_bidauctiondepot
            }
            if site in site_map:
                site_map[site](url, start_page, end_page)
            else:
                print(f"🔥 ERROR: No scraper found for site '{site}'")

        except Exception as e:
            print(f"\n🔥🔥🔥 A CRITICAL ERROR occurred during the scraping process: {e} 🔥🔥🔥")
            traceback.print_exc()
            self.ui['status'].error(f"An unexpected error occurred during scraping: {e}")
        finally:
            if self.browser:
                try:
                    print("   -> Finalizing run, closing browser...")
                    self.loop.run_until_complete(self.browser.close())
                    self.loop.run_until_complete(self.playwright.stop())
                    print("   -> Browser closed.")
                except Exception as e:
                    print(f"   -> NOTE: Harmless error during final browser shutdown: {e}")
                    pass
            print(f"🏁🏁🏁 Scraper run finished for {site}. 🏁🏁🏁\n")

        # Final summary report
        if self.products:
            avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
            print("--- Scraping Summary ---")
            print(f"  Total Items Scraped: {len(self.products)}")
            print(f"  Average Recovery: {avg_recovery:.1f}%")
            print("------------------------\n")
        else:
            print("--- Scraping Summary ---")
            print("  No items were successfully scraped.")
            print("------------------------\n")

        return self.products

    def process_item(self, title, product_url, image_url, sold_price_text, item_index, total_items_on_page, category=None):
        try:
            self.ui['status'].info(f"Processing item {item_index}/{total_items_on_page}: {title[:40]}...")
            sold_price_float = round(float(sold_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            
            ai_result = self.get_retail_price(title, image_url)
            if ai_result:
                price_part, link_part = ai_result.split(',', 1)
                retail_price_float = round(float(price_part.strip().replace('$', '')), 2)
                
                if retail_price_float > 0:
                    percentage = round((sold_price_float / retail_price_float) * 100, 2)
                    self.percentages.append(percentage)
                    
                    data = {"Link": product_url, "Title": title, "Sold Price": f"${sold_price_float:,.2f}", "Retail Price": f"${retail_price_float:,.2f}", "Recovery": f"{percentage:.1f}%"}
                    if category: data["Category"] = category
                    self.products.append(data)
                    
                    print(f"  [SUCCESS] '{title[:40]}...' | Sold: ${sold_price_float:.2f} | Retail: ${retail_price_float:.2f} | Recovery: {percentage:.1f}%")
                    
                    df = pd.DataFrame(self.products)
                    self.ui['dataframe'].dataframe(df, use_container_width=True)
                    
                    avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
                    self.ui['metrics']['lots'].metric("Lots Scraped", len(self.products))
                    self.ui['metrics']['recovery'].metric("Average Recovery", f"{avg_recovery:.1f}%")
                    self.ui['progress'].progress(item_index / total_items_on_page, text=f"Page Progress: {item_index}/{total_items_on_page}")
            else:
                print(f"  [SKIPPED] AI could not find a retail price for '{title[:30]}...'.")
                self.ui['status'].warning(f"Skipping '{title[:30]}...' - AI could not find a retail price.")
        except Exception as e:
            print(f"  [ERROR] Skipping item '{title[:30]}...' due to an error: {e}")
            traceback.print_exc()
            self.ui['status'].warning(f"Skipping item '{title[:30]}...' due to error: {e}")

    def process_item_no_ai(self, title, product_url, sold_price_text, retail_price_text, item_index, total_items_on_page, category=None):
        try:
            sold_price_float = round(float(sold_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            retail_price_float = round(float(retail_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            
            if retail_price_float > 0:
                percentage = round((sold_price_float / retail_price_float) * 100, 2)
                self.percentages.append(percentage)
                
                data = {"Link": product_url, "Title": title, "Sold Price": f"${sold_price_float:,.2f}", "Retail Price": f"${retail_price_float:,.2f}", "Recovery": f"{percentage:.1f}%"}
                if category: data["Category"] = category
                self.products.append(data)
                
                print(f"  [SUCCESS] '{title[:40]}...' | Sold: ${sold_price_float:.2f} | Retail: ${retail_price_float:.2f} | Recovery: {percentage:.1f}%")
                
                df = pd.DataFrame(self.products)
                self.ui['dataframe'].dataframe(df, use_container_width=True)
                
                avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
                self.ui['metrics']['lots'].metric("Lots Scraped", len(self.products))
                self.ui['metrics']['recovery'].metric("Average Recovery", f"{avg_recovery:.1f}%")
                self.ui['progress'].progress(item_index / total_items_on_page, text=f"Page Progress: {item_index}/{total_items_on_page}")
        except Exception as e:
            print(f"  [ERROR] Skipping item '{title[:30]}...' due to an error: {e}")
            traceback.print_exc()
            self.ui['status'].warning(f"Skipping item '{title[:30]}...' due to error: {e}")

    # --- SCRAPERS START HERE ---

    def scrape_hibid(self, url, start_page, end_page):
        print("\n--- Starting HiBid Scraper ---")
        base_url = url.split("/catalog")[0]
        page = start_page
        while self.running and (end_page == 0 or page <= end_page):
            print(f"  -> Navigating to HiBid Page: {page}")
            self.ui['status'].info(f"Navigating to HiBid Page: {page}...")
            current_url = f"{url}{'&' if '?' in url else '?'}apage={page}"
            
            self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            try:
                self.loop.run_until_complete(self.page.wait_for_selector("h2.lot-title", timeout=40000))
            except Exception:
                print("  -> No more items or pages found. Scraping complete.")
                self.ui['status'].success("No more pages found. Scraping complete.")
                break

            html = self.loop.run_until_complete(self.page.content())
            soup = BeautifulSoup(html, 'html.parser')
            products = [p for p in soup.find_all("app-lot-tile") if p.find("strong", class_="lot-price-realized")]
            if not products:
                print("  -> No more priced items on this page. Scraping complete.")
                self.ui['status'].success("No more items with prices on this page. Scraping complete.")
                break

            print(f"  -> Found {len(products)} priced items on page {page}.")
            for i, p in enumerate(products, 1):
                if not self.running: break
                try:
                    title_tag = p.find("h2", class_="lot-title")
                    link_tag = p.find("a")
                    img_tag = p.find("img", class_="lot-thumbnail img-fluid")
                    price_tag = p.find("strong", class_="lot-price-realized")
                    
                    if all([title_tag, link_tag, img_tag, price_tag]):
                        self.process_item(
                            title=title_tag.text.strip(),
                            product_url=base_url + link_tag.get("href"),
                            image_url=img_tag['src'],
                            sold_price_text=price_tag.text,
                            item_index=i,
                            total_items_on_page=len(products)
                        )
                    else:
                        print(f"  [WARN] Skipping item {i} on page {page} due to missing data.")
                except Exception as e:
                    print(f"  [ERROR] Could not process item {i} on page {page}: {e}")
                time.sleep(0.5)
            page += 1

    def generate_next_bidllama_urls(self, original_url, total_pages=500):
        if "#" not in original_url: return [original_url]
        base_url, encoded_fragment = original_url.split("#", 1)
        padding = "=" * (4 - len(encoded_fragment) % 4)
        try:
            import base64
            decoded = base64.b64decode(encoded_fragment + padding).decode()
            current_page = int(re.search(r'page=(\d+)', decoded).group(1))
            urls = []
            for page in range(current_page, current_page + total_pages):
                new_decoded = re.sub(r'page=\d+', f'page={page}', decoded)
                new_encoded = base64.b64encode(new_decoded.encode()).decode().rstrip("=")
                urls.append(base_url + "#" + new_encoded)
            return urls
        except Exception:
            return [original_url]

    def scrape_biddingkings(self, url, start_page, end_page):
        print("\n--- Starting BiddingKings Scraper ---")
        base_url = "https://auctions.biddingkings.com"
        page = start_page
        while self.running and (end_page == 0 or page <= end_page):
            current_url = f"{url}?page={page}"
            print(f"  -> Scraping BiddingKings Page: {page}")
            self.ui['status'].info(f"Scraping BiddingKings Page: {page}")
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            try:
                self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
                time.sleep(3)
                self.loop.run_until_complete(self.page.wait_for_selector("div[class*='lot-repeater-index']", timeout=40000))
            except Exception:
                print("  -> No more items or pages found. Scraping complete.")
                self.ui['status'].success("No more pages found. Scraping complete.")
                break
            
            html = self.loop.run_until_complete(self.page.content())
            soup = BeautifulSoup(html, 'html.parser')
            products = soup.find_all("div", class_=re.compile(r'lot-repeater-index'))
            if not products:
                print("  -> No more items on this page. Scraping complete.")
                self.ui['status'].success("No more items. Scraping complete.")
                break
                
            print(f"  -> Found {len(products)} items on page {page}.")
            for i, p in enumerate(products, 1):
                if not self.running: break
                try:
                    link_tag = p.find("a")
                    img_tag = p.find("img")
                    
                    if link_tag and img_tag:
                        title = link_tag.text.strip()
                        product_url = base_url + link_tag.get("href")
                        
                        self.loop.run_until_complete(self.page.goto(product_url, wait_until='networkidle', timeout=60000))
                        product_html = self.loop.run_until_complete(self.page.content())
                        product_soup = BeautifulSoup(product_html, 'html.parser')
                        price_tag = product_soup.find("span", class_="sold-amount")
                        
                        if price_tag:
                            self.process_item(
                                title=title,
                                product_url=product_url,
                                image_url=img_tag.get('ng-src'),
                                sold_price_text=price_tag.text,
                                item_index=i,
                                total_items_on_page=len(products)
                            )
                        else:
                            print(f"  [WARN] No price found for '{title[:40]}...'. Skipping.")
                except Exception as e:
                    print(f"  [ERROR] Could not process item {i} on page {page}: {e}")
                time.sleep(0.5)
            page += 1

    def scrape_bidllama(self, url, start_page, end_page):
        print("\n--- Starting BidLlama Scraper ---")
        base_url = "https://bid.bidllama.com"
        page = start_page
        paginated_urls = self.generate_next_bidllama_urls(url)
        
        while self.running and (end_page == 0 or page <= end_page):
            if page - 1 >= len(paginated_urls):
                print("  -> Reached end of generated URLs. Scraping complete.")
                self.ui['status'].success("Reached end of generated URLs.")
                break
                
            current_url = paginated_urls[page-1]
            print(f"  -> Scraping BidLlama Page: {page}")
            self.ui['status'].info(f"Scraping BidLlama Page: {page}")
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            try:
                self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
                time.sleep(5)
                self.loop.run_until_complete(self.page.wait_for_selector("p.item-lot-number", timeout=40000))
            except Exception:
                print("  -> No more items or pages found. Scraping complete.")
                self.ui['status'].success("No more pages found. Scraping complete.")
                break
            
            html = self.loop.run_until_complete(self.page.content())
            soup = BeautifulSoup(html, 'html.parser')
            item_container = soup.find("div", class_="item-row grid")
            if not item_container:
                print("  -> No item container found on page. Scraping complete.")
                self.ui['status'].success("No item container found on page. Scraping complete.")
                break
            
            products = item_container.find_all("div", recursive=False)
            if not products:
                print("  -> No more items on this page. Scraping complete.")
                self.ui['status'].success("No more items. Scraping complete.")
                break

            print(f"  -> Found {len(products)} items on page {page}.")
            for i, p in enumerate(products, 1):
                if not self.running: break
                try:
                    title_tag = p.find("p", class_="item-title")
                    img_container = p.find("p", class_="item-image")
                    price_tag = p.find("p", class_="item-current-bid")
                    
                    if title_tag and img_container and price_tag:
                        link_tag = img_container.find("a")
                        img_tag = img_container.find("img")
                        if link_tag and img_tag:
                            product_url = base_url + link_tag.get("href")
                            image_url = img_tag.get('src', '')
                            if not image_url.startswith('http'):
                                image_url = "https:" + image_url
                            
                            self.process_item(
                                title=title_tag.text.strip(),
                                product_url=product_url,
                                image_url=image_url,
                                sold_price_text=price_tag.text,
                                item_index=i,
                                total_items_on_page=len(products)
                            )
                        else:
                            print(f"  [WARN] Skipping item {i} on page {page} due to missing link/image tags.")
                except Exception as e:
                    print(f"  [ERROR] Could not process item {i} on page {page}: {e}")
                time.sleep(0.5)
            page += 1

    def scrape_nellis(self, url, start_page, end_page):
        print("\n--- Starting Nellis Scraper ---")
        base_url = "https://www.nellisauction.com"
        current_url = url
        if not current_url.startswith("http"): current_url = f"https://{current_url}"
            
        links = []
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                print(f"  -> Fetching Nellis page {page}...")
                self.ui['status'].info(f"Fetching Nellis page {page}...")
                req = requests.get(current_url, headers=self.headers, timeout=20)
                
                if req.status_code != 200:
                    print(f"  -> 🔥 FAILED to fetch page {page}. Status code: {req.status_code}")
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {req.status_code}")
                    break
                    
                soup = BeautifulSoup(req.text, "html.parser")
                products = soup.find_all("li", class_="__list-item-base")
                if not products: 
                    print("  -> No more product links on page. Ending page scan.")
                    break
                    
                for p in products:
                    link_tag = p.find("a")
                    if link_tag and link_tag.get("href"): links.append(base_url + link_tag.get("href"))
                        
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                next_page = next((link.get("href") for link in soup.find_all("a", class_="__pagination-link") if link.text.strip() == str(page + 1)), None)
                if not next_page: 
                    print("  -> No 'next page' button found. Ending page scan.")
                    break
                    
                current_url = base_url + next_page
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  -> 🔥 ERROR while fetching page {page}: {str(e)}")
                traceback.print_exc()
                self.ui['status'].error(f"Error while fetching page {page}: {str(e)}")
                break
        
        total_products = len(links)
        print(f"  -> Found {total_products} total product links. Now processing each item...")
        
        for i, link in enumerate(links, 1):
            if not self.running: break
            try:
                req = requests.get(link, headers=self.headers, timeout=20)
                soup = BeautifulSoup(req.text, "html.parser")
                title = soup.find("h1").text if soup.find("h1") else "Unknown Title"
                
                sold_price = next(iter([x.text for x in soup.find_all("p", class_=re.compile(r'text-gray-900')) if "$" in x.text]), " ")
                
                if sold_price != " ":
                    retail_price_tmp = soup.find_all("div", class_="flex flex-col text-left")
                    retail_price = next(iter([x.text.replace("Estimated Retail Price", "").strip() for x in retail_price_tmp if "Estimated Retail Price" in x.text]), " ")
                    
                    if retail_price == " ":
                        retail_price_tmp = soup.find_all("div", class_=re.compile(r'grid grid-cols'))
                        retail_price = next(iter([x.text.replace("Estimated Retail Price", "").strip() for x in retail_price_tmp if "Estimated Retail Price" in x.text]), " ")
                    
                    if retail_price != " ":
                        category_tmp = soup.find("a", class_=re.compile(r'flex items-center gap-1'))
                        category = category_tmp.text.strip() if category_tmp else " "
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price, retail_price_text=retail_price, item_index=i, total_items_on_page=total_products, category=category)
                time.sleep(0.1)
                
            except Exception as e:
                print(f"  -> 🔥 ERROR processing product {i} ({link}): {str(e)}")
                self.ui['status'].warning(f"Error processing product {i}: {str(e)}")

    def scrape_bidfta(self, url, start_page, end_page):
        print("\n--- Starting BidFTA Scraper ---")
        base_url = "https://www.bidfta.com"
        current_url = url.split("?")[0].rsplit("/", 1)[0]
        
        links = set()
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                page_url = f"{current_url}/{page}"
                print(f"  -> Fetching BidFTA page {page} from {page_url}...")
                req = requests.get(page_url, headers=self.headers, timeout=20)
                
                if req.status_code != 200:
                    print(f"  -> Page {page} not found or failed to load. Ending scan.")
                    break
                    
                soup = BeautifulSoup(req.text, "html.parser")
                div = soup.find("div", class_=re.compile(r'grid-cols-1'))
                
                if not div:
                    print("  -> No product container found. Ending scan.")
                    break
                    
                products = div.find_all("div", class_="block")
                if not products:
                    print("  -> No product blocks found. Ending scan.")
                    break
                    
                new_links_count = 0
                for p in products:
                    link_tag = p.find("a")
                    if link_tag and link_tag.get("href"):
                        product_url = base_url + link_tag.get("href")
                        if product_url not in links:
                            links.add(product_url)
                            new_links_count += 1
                
                if new_links_count == 0 and page > start_page:
                    print("  -> No new links found on this page. Ending scan.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  -> 🔥 ERROR while fetching page {page}: {str(e)}")
                break
        
        total_products = len(links)
        print(f"  -> Found {total_products} total product links. Now processing each item...")
        
        for i, link in enumerate(list(links), 1):
            if not self.running: break
            try:
                req = requests.get(link, headers=self.headers, timeout=20)
                soup = BeautifulSoup(req.text, "html.parser")
                
                title = soup.find("h2").text.strip() if soup.find("h2") else "Unknown Title"
                
                sold_price_elem = soup.find("div", string=re.compile("CURRENT BID"))
                sold_price = sold_price_elem.find_next_sibling("div").text.strip() if sold_price_elem else " "
                
                if sold_price != " ":
                    retail_price_elem = soup.find("div", string=re.compile("MSRP"))
                    retail_price = retail_price_elem.find_next_sibling("div").text.strip() if retail_price_elem else " "
                    
                    if retail_price != " ":
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price, retail_price_text=retail_price, item_index=i, total_items_on_page=total_products)
                time.sleep(0.1)
                
            except Exception as e:
                print(f"  -> 🔥 ERROR processing product {i} ({link}): {str(e)}")

    def scrape_macbid(self, url, start_page, end_page):
        print("\n--- Starting MAC.bid Scraper ---")
        base_url = "https://www.mac.bid"
        
        try:
            print("  -> Navigating to initial URL...")
            self.loop.run_until_complete(self.page.goto(url, wait_until='networkidle', timeout=60000))
            
            prev_product_count = 0
            scroll_attempts = 0
            max_scroll_attempts = 20 # To prevent infinite loops
            
            while self.running and scroll_attempts < max_scroll_attempts:
                print(f"  -> Scrolling to load more items (Attempt {scroll_attempts + 1})...")
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, 'html.parser')
                products = soup.find_all("div", class_="d-block w-100 border-bottom")
                
                current_product_count = len(products)
                self.ui['metrics']['lots'].metric("Lots Found", current_product_count)
                
                if current_product_count == prev_product_count:
                    if soup.find("div", class_="spinner-grow") is None:
                        print("  -> No more items are loading. Finalizing list.")
                        break
                    else:
                        print("  -> Spinner visible, waiting for content...")
                        time.sleep(3)
                else:
                    prev_product_count = current_product_count
                    self.loop.run_until_complete(self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)'))
                    time.sleep(2)
                
                scroll_attempts += 1

            final_html = self.loop.run_until_complete(self.page.content())
            final_soup = BeautifulSoup(final_html, 'html.parser')
            products_found = final_soup.find_all("div", class_="d-block w-100 border-bottom")
            
            total_products = len(products_found)
            print(f"  -> Found {total_products} total products. Now processing each item...")
            
            for i, product in enumerate(products_found, 1):
                if not self.running: break
                try:
                    if product.find("p", class_="badge badge-success") is not None:
                        title = product.find("p").text.strip()
                        sold_price = product.find("p", class_="badge badge-success").text.replace("Won for $", "").strip()
                        retail_price = product.find("p", class_="font-size-sm").text.replace("Retails for $", "").strip()
                        link_tag = product.find("a")
                        link = base_url + link_tag["href"] if link_tag and link_tag.get("href") else ""
                        
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price, retail_price_text=retail_price, item_index=i, total_items_on_page=total_products)
                    time.sleep(0.1)
                except Exception as e:
                    print(f"  -> 🔥 ERROR processing product {i}: {str(e)}")

        except Exception as e:
            print(f"  -> 🔥 CRITICAL ERROR in MAC.bid scraper: {str(e)}")
            traceback.print_exc()

    def scrape_astock(self, url, start_page, end_page):
        print("\n--- Starting A-Stock Scraper ---")
        base_url = url.split("?")[0]
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                current_url = f"{base_url}?page={page}"
                print(f"  -> Fetching A-Stock page {page} from {current_url}...")
                response = requests.get(current_url, headers=self.headers, timeout=20)
                
                if response.status_code != 200:
                    print(f"  -> Page {page} failed to load. Ending scan.")
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                sections = soup.find_all("section")
                
                if not sections:
                    print("  -> No more items found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                for i, section in enumerate(sections, 1):
                    if not self.running: break
                    try:
                        title_elem = section.find("h2", class_="title inlinebidding")
                        if not title_elem: continue
                            
                        link = "https://a-stock.bid" + title_elem.find("a")["href"] if title_elem.find("a") else "N/A"
                        title = title_elem.text.split("-", 1)[-1].strip()
                        
                        sold_price_text = section.find("p", class_="bids").text.strip()
                        retail_price_text = section.find("div", class_="listing-auction-row-retail-value").text.strip()
                        
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price_text, retail_price_text=retail_price_text, item_index=i, total_items_on_page=len(sections))
                        
                    except Exception as e:
                        print(f"  [WARN] Could not process item {i} on page {page}: {e}")
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  -> 🔥 ERROR fetching page {page}: {str(e)}")
                break

    def scrape_702auctions(self, url, start_page, end_page):
        print("\n--- Starting 702Auctions Scraper ---")
        auction_base_url = "https://bid.702auctions.com"
        base_url = url.split("?")[0]
        page = start_page - 1 if start_page > 0 else 0
        
        while self.running and (end_page == 0 or page < end_page):
            try:
                current_url = f"{base_url}?ViewStyle=list&StatusFilter=completed_only&SortFilterOptions=0&page={page}"
                print(f"  -> Fetching 702Auctions page {page} from {current_url}...")
                response = requests.get(current_url, headers=self.headers, timeout=20)
                
                if response.status_code != 200:
                    print(f"  -> Page {page} failed to load. Ending scan.")
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                sections = soup.find_all("section")
                
                if not sections:
                    print("  -> No more items found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page + 1)
                
                for i, section in enumerate(sections, 1):
                    if not self.running: break
                    try:
                        title_elem = section.find("h2", class_="title inlinebidding")
                        if not title_elem: continue
                        
                        subtitle_elem = section.find("h3", class_="subtitle")
                        link = auction_base_url + subtitle_elem.find("a")["href"] if subtitle_elem and subtitle_elem.find("a") else "N/A"
                        title = title_elem.text.split("-", 1)[-1].strip()
                        
                        sold_price_text = section.find("span", class_="NumberPart").text.strip()
                        retail_price_text = subtitle_elem.text.strip() if subtitle_elem else "0"
                        
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price_text, retail_price_text=retail_price_text, item_index=i, total_items_on_page=len(sections))
                        
                    except Exception as e:
                        print(f"  [WARN] Could not process item {i} on page {page}: {e}")
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  -> 🔥 ERROR fetching page {page}: {str(e)}")
                break

    def scrape_vista(self, url, start_page, end_page):
        print("\n--- Starting Vista Auction Scraper ---")
        base_url = url.split("?")[0]
        vista_base_url = "https://vistaauction.com"
        page = start_page - 1 if start_page > 0 else 0
        
        while self.running and (end_page == 0 or page < end_page):
            try:
                current_url = f"{base_url}?page={page}"
                print(f"  -> Fetching Vista Auction page {page}...")
                self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
                time.sleep(5)
                
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, "html.parser")
                sections = soup.find_all("section")
                
                if not sections:
                    print("  -> No more items found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page + 1)
                
                for i, section in enumerate(sections, 1):
                    if not self.running: break
                    try:
                        title_elem = section.find("h2", class_="title inlinebidding")
                        if not title_elem: continue
                        
                        subtitle_elem = section.find("h3", class_="subtitle")
                        link = vista_base_url + subtitle_elem.find("a")["href"] if subtitle_elem and subtitle_elem.find("a") else "N/A"
                        title = re.sub(r'^Lot \d+\s*-\s*', '', title_elem.text.strip()).strip()
                        
                        sold_price_text = section.find("span", class_="NumberPart").text.strip()
                        retail_price_text = subtitle_elem.text.strip() if subtitle_elem else "0"
                        
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price_text, retail_price_text=retail_price_text, item_index=i, total_items_on_page=len(sections))
                        
                    except Exception as e:
                        print(f"  [WARN] Could not process item {i} on page {page}: {e}")
                
                page += 1
            except Exception as e:
                print(f"  -> 🔥 ERROR fetching page {page}: {str(e)}")
                break

    def scrape_bidsoflo(self, url, start_page, end_page):
        print("\n--- Starting BidSoflo Scraper ---")
        base_url = "https://bid.bidsoflo.us"
        page = start_page
        
        try:
            print(f"  -> Navigating to initial URL: {url}")
            self.loop.run_until_complete(self.page.goto(url, wait_until='networkidle', timeout=60000))
            time.sleep(2)
        
            while self.running and (end_page == 0 or page <= end_page):
                print(f"  -> Processing BidSoflo page {page}")
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, 'html.parser')
                
                products = soup.find_all("div", class_="row mr-1")
                print(f"  -> Found {len(products)} potential items on page.")
                
                for i, p in enumerate(products, 1):
                    if not self.running: break
                    try:
                        tooltip = p.find("div", class_="tooltip-demos")
                        if not tooltip: continue
                        
                        desc_div = next(iter([div for div in tooltip.find_all("div", recursive=False) if "Item Description" in div.text]), None)
                        title = desc_div.text.replace("Item Description", "").strip() if desc_div else None
                        
                        if title:
                            retail_div = next(iter([div for div in tooltip.find_all("div", recursive=False) if "Retail Cost:" in div.text]), None)
                            retail_price = retail_div.text.replace("Retail Cost:", "").strip() if retail_div else None
                            
                            price_div = p.find("div", class_="font-bold text-body")
                            sold_price = price_div.text.replace("Final Bid :", "").strip() if price_div and "Final Bid" in price_div.text else None
                            
                            if retail_price and sold_price:
                                link_tag = p.find("a")
                                link = base_url + link_tag["href"] if link_tag else "N/A"
                                self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price, retail_price_text=retail_price, item_index=i, total_items_on_page=len(products))
                    except Exception as e:
                        print(f"  [WARN] Could not process item {i} on page {page}: {e}")

                next_page_elem = soup.find("li", class_="page-item", string=re.compile("Next"))
                if next_page_elem and next_page_elem.find("a"):
                    print("  -> Found 'Next' page button. Clicking...")
                    self.loop.run_until_complete(self.page.click('li.page-item:has-text("Next") a'))
                    page += 1
                    time.sleep(3)
                    self.ui['metrics']['pages'].metric("Pages Scraped", page)
                else:
                    print("  -> No more pages found. Scraping complete.")
                    break
        except Exception as e:
            print(f"  -> 🔥 CRITICAL ERROR in BidSoflo scraper: {str(e)}")
            traceback.print_exc()

    def scrape_bidauctiondepot(self, url, start_page, end_page):
        print("\n--- Starting BidAuctionDepot Scraper ---")
        base_url = "https://bidauctiondepot.com/productView/"
        page = start_page
        last_seen_lot_id = ""
        
        try:
            print(f"  -> Navigating to initial URL: {url}")
            self.loop.run_until_complete(self.page.goto(url, wait_until='networkidle', timeout=60000))
            time.sleep(3)
        
            while self.running and (end_page == 0 or page <= end_page):
                print(f"  -> Processing BidAuctionDepot page {page}")
                self.loop.run_until_complete(self.page.wait_for_selector('div[class*="card grid-card"]', timeout=25000))
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, 'html.parser')
                
                products = soup.find_all('div', class_=lambda c: c and "card grid-card" in c)
                if not products:
                    print("  -> No products found. Scraping complete.")
                    break
                
                print(f"  -> Found {len(products)} items on page {page}.")
                
                # Check for duplicate pages
                first_lot_id = products[0].get("id")
                if first_lot_id and first_lot_id == last_seen_lot_id:
                    print("  -> Duplicate page content detected. Ending scrape.")
                    break
                last_seen_lot_id = first_lot_id

                for i, p in enumerate(products, 1):
                    if not self.running: break
                    try:
                        title = p.find("h5").text.strip()
                        retail_price_text = p.select_one("h6.galleryPrice.rtlrPrice").text
                        sold_price_text = p.find("span", class_="curBidAmtt").text
                        link_id = p.get("id").replace("lot-", "")
                        link = base_url + link_id
                        
                        self.process_item_no_ai(title=title, product_url=link, sold_price_text=sold_price_text, retail_price_text=retail_price_text, item_index=i, total_items_on_page=len(products))
                    except Exception as e:
                         print(f"  [WARN] Could not process item {i} on page {page}. Skipping.")

                next_button = self.loop.run_until_complete(self.page.query_selector("a[aria-label='Go to next page']"))
                if next_button:
                    print("  -> Found 'Next' page button. Clicking...")
                    self.loop.run_until_complete(next_button.click())
                    page += 1
                    time.sleep(4)
                    self.ui['metrics']['pages'].metric("Pages Scraped", page)
                else:
                    print("  -> No more pages found. Scraping complete.")
                    break
        except Exception as e:
            print(f"  -> 🔥 CRITICAL ERROR in BidAuctionDepot scraper: {str(e)}")
            traceback.print_exc()

