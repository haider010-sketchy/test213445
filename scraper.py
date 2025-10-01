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
        self.running = False
        self._is_running = False
        if self.browser:
            try:
                self.loop.run_until_complete(self.browser.close())
                self.loop.run_until_complete(self.playwright.stop())
            except:
                pass

    def setup_gemini(self):
        try:
            if not self.gemini_api_keys:
                self.ui['status'].warning("No Gemini API keys found.")
                return

            api_key = self.gemini_api_keys[self.current_api_key_index]
            self.gemini_client = genai.Client(api_key=api_key)
            self.ui['status'].info(f"AI price lookup enabled with Gemini Client (API Key {self.current_api_key_index + 1})")

        except Exception as e:
            self.ui['status'].error(f"An unexpected error occurred setting up Gemini AI: {e}.")
            self.gemini_client = None
            traceback.print_exc()

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
                    self.ui['status'].info(f"Rate limit reached. Waiting {wait_time:.0f} seconds...")
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
                
                response = requests.get(image_url, headers=self.headers, stream=True, timeout=15)
                if response.status_code != 200:
                    print(f"Failed to download image: {image_url}")
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
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt_text},
                            {"inline_data": {"mime_type": "image/png", "data": image_bytes}}
                        ]
                    }
                ]
                
                self.record_request()
                
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents
                )

                response_text = response.text.strip()
                match = re.search(r'([\d,]+\.?\d*)\s*,\s*(https?://\S+)', response_text)
                if match:
                    price = match.group(1).replace(',', '')
                    link = match.group(2)
                    return f"{price}, {link}"
                else:
                    print(f"AI response format invalid: {response_text}")
                    raise ValueError("Invalid AI response format")

            except Exception as e:
                error_str = str(e)
                
                if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
                    self.ui['status'].warning("Rate limit hit! Waiting 30 seconds before retry...")
                    time.sleep(30)
                    
                    try:
                        self.record_request()
                        response = self.gemini_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=contents
                        )
                        response_text = response.text.strip()
                        match = re.search(r'([\d,]+\.?\d*)\s*,\s*(https?://\S+)', response_text)
                        if match:
                            price = match.group(1).replace(',', '')
                            link = match.group(2)
                            return f"{price}, {link}"
                    except Exception as retry_e:
                        self.ui['status'].warning(f"Retry failed: {retry_e}")
                
                print("\n--- ERROR IN get_retail_price ---")
                traceback.print_exc()
                print("---------------------------------\n")
                
                self.current_api_key_index = (self.current_api_key_index + 1) % len(self.gemini_api_keys)
                self.ui['status'].warning(f"Switching to Gemini API Key {self.current_api_key_index + 1} due to error.")
                self.setup_gemini()
                self.request_times = []
        
        self.ui['status'].error("All Gemini API keys failed. Disabling AI for this session.")
        self.gemini_client = None
        return None

    def run(self, site, url, start_page, end_page):
        try:
            selenium_sites = ["HiBid", "BiddingKings", "BidLlama", "MAC.bid", "Vista", "BidAuctionDepot", "BidSoflo"]
            
            if site in selenium_sites:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

                # Initialize Playwright browser
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                
                async def init_browser():
                    self.playwright = await async_playwright().start()
                    self.browser = await self.playwright.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
                    )
                    self.page = await self.browser.new_page()
                    await stealth_async(self.page)
                
                self.loop.run_until_complete(init_browser())
            
            if site == "HiBid": 
                self.scrape_hibid(url, start_page, end_page)
            elif site == "BiddingKings": 
                self.scrape_biddingkings(url, start_page, end_page)
            elif site == "BidLlama": 
                self.scrape_bidllama(url, start_page, end_page)
            elif site == "Nellis": 
                self.scrape_nellis(url, start_page, end_page)
            elif site == "BidFTA": 
                self.scrape_bidfta(url, start_page, end_page)
            elif site == "MAC.bid": 
                self.scrape_macbid(url, start_page, end_page)
            elif site == "A-Stock":
                self.scrape_astock(url, start_page, end_page)
            elif site == "702Auctions":
                self.scrape_702auctions(url, start_page, end_page)
            elif site == "Vista":
                self.scrape_vista(url, start_page, end_page)
            elif site == "BidSoflo":
                self.scrape_bidsoflo(url, start_page, end_page)
            elif site == "BidAuctionDepot":
                self.scrape_bidauctiondepot(url, start_page, end_page)
        except Exception as e:
            self.ui['status'].error(f"An unexpected error occurred during scraping: {e}")
            traceback.print_exc()
        finally:
            if self.browser:
                try:
                    self.loop.run_until_complete(self.browser.close())
                    self.loop.run_until_complete(self.playwright.stop())
                except:
                    pass
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
                    
                    data = {
                        "Link": product_url, 
                        "Title": title, 
                        "Sold Price": f"${sold_price_float:,.2f}",
                        "Retail Price": f"${retail_price_float:,.2f}",
                        "Recovery": f"{percentage:.1f}%"
                    }
                    
                    if category:
                        data["Category"] = category
                    
                    self.products.append(data)
                    
                    df = pd.DataFrame(self.products)
                    self.ui['dataframe'].dataframe(df, use_container_width=True)
                    
                    avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
                    self.ui['metrics']['lots'].metric("Lots Scraped", len(self.products))
                    self.ui['metrics']['recovery'].metric("Average Recovery", f"{avg_recovery:.1f}%")
                    self.ui['progress'].progress(item_index / total_items_on_page, text=f"Page Progress: {item_index}/{total_items_on_page}")
            else:
                self.ui['status'].warning(f"Skipping '{title[:30]}...' - AI could not find a retail price.")
        except Exception as e:
            self.ui['status'].warning(f"Skipping item '{title[:30]}...' due to error: {e}")

    def process_item_no_ai(self, title, product_url, sold_price_text, retail_price_text, item_index, total_items_on_page, category=None):
        """Process items that already have retail prices (no AI needed)"""
        try:
            self.ui['status'].info(f"Processing item {item_index}/{total_items_on_page}: {title[:40]}...")
            sold_price_float = round(float(sold_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            retail_price_float = round(float(retail_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            
            if retail_price_float > 0:
                percentage = round((sold_price_float / retail_price_float) * 100, 2)
                self.percentages.append(percentage)
                
                data = {
                    "Link": product_url, 
                    "Title": title, 
                    "Sold Price": f"${sold_price_float:,.2f}",
                    "Retail Price": f"${retail_price_float:,.2f}",
                    "Recovery": f"{percentage:.1f}%"
                }
                
                if category:
                    data["Category"] = category
                
                self.products.append(data)
                
                df = pd.DataFrame(self.products)
                self.ui['dataframe'].dataframe(df, use_container_width=True)
                
                avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
                self.ui['metrics']['lots'].metric("Lots Scraped", len(self.products))
                self.ui['metrics']['recovery'].metric("Average Recovery", f"{avg_recovery:.1f}%")
                self.ui['progress'].progress(item_index / total_items_on_page, text=f"Page Progress: {item_index}/{total_items_on_page}")
        except Exception as e:
            self.ui['status'].warning(f"Skipping item '{title[:30]}...' due to error: {e}")

    # AI-Powered Scrapers (HiBid, BiddingKings, BidLlama)
    def scrape_hibid(self, url, start_page, end_page):
        base_url = url.split("/catalog")[0]
        page = start_page
        while self.running and (end_page == 0 or page <= end_page):
            self.ui['status'].info(f"Navigating to HiBid Page: {page}...")
            current_url = f"{url}{'&' if '?' in url else '?'}apage={page}"
            
            self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            try:
                self.loop.run_until_complete(self.page.wait_for_selector("h2.lot-title", timeout=40000))
            except:
                self.ui['status'].success("No more pages found. Scraping complete.")
                break

            html = self.loop.run_until_complete(self.page.content())
            soup = BeautifulSoup(html, 'html.parser')
            products = [p for p in soup.find_all("app-lot-tile") if p.find("strong", class_="lot-price-realized")]
            if not products:
                self.ui['status'].success("No more items with prices on this page. Scraping complete.")
                break

            for i, p in enumerate(products, 1):
                if not self.running: break
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
        base_url = "https://auctions.biddingkings.com"
        page = start_page
        while self.running and (end_page == 0 or page <= end_page):
            current_url = f"{url}?page={page}"
            self.ui['status'].info(f"Scraping BiddingKings Page: {page}")
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
            time.sleep(3)
            
            try:
                self.loop.run_until_complete(self.page.wait_for_selector("div[class*='lot-repeater-index']", timeout=40000))
            except:
                self.ui['status'].success("No more pages found. Scraping complete.")
                break
            
            html = self.loop.run_until_complete(self.page.content())
            soup = BeautifulSoup(html, 'html.parser')
            products = soup.find_all("div", class_=re.compile(r'lot-repeater-index'))
            if not products:
                self.ui['status'].success("No more items. Scraping complete.")
                break
                
            for i, p in enumerate(products, 1):
                if not self.running: break
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
                time.sleep(0.5)
            page += 1

    def scrape_bidllama(self, url, start_page, end_page):
        base_url = "https://bid.bidllama.com"
        page = start_page
        paginated_urls = self.generate_next_bidllama_urls(url)
        
        while self.running and (end_page == 0 or page <= end_page):
            if page - 1 >= len(paginated_urls):
                self.ui['status'].success("Reached end of generated URLs.")
                break
                
            current_url = paginated_urls[page-1]
            self.ui['status'].info(f"Scraping BidLlama Page: {page}")
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
            time.sleep(5)
            
            try:
                self.loop.run_until_complete(self.page.wait_for_selector("p.item-lot-number", timeout=40000))
            except:
                self.ui['status'].success("No more pages found. Scraping complete.")
                break
            
            html = self.loop.run_until_complete(self.page.content())
            soup = BeautifulSoup(html, 'html.parser')
            item_container = soup.find("div", class_="item-row grid")
            if not item_container:
                self.ui['status'].success("No item container found on page. Scraping complete.")
                break
            
            products = item_container.find_all("div", recursive=False)
            if not products:
                self.ui['status'].success("No more items. Scraping complete.")
                break

            for i, p in enumerate(products, 1):
                if not self.running: break
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
                time.sleep(0.5)
            page += 1

    # Direct Price Scrapers (Nellis, BidFTA, MAC.bid, A-Stock, 702Auctions)
    def scrape_nellis(self, url, start_page, end_page):
        """Scrape Nellis Auction - uses requests (no AI needed, has retail prices)"""
        base_url = "https://www.nellisauction.com"
        current_url = url
        if not current_url.startswith("http"):
            current_url = f"https://{current_url}"
            
        links = []
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                self.ui['status'].info(f"Fetching Nellis page {page}...")
                req = requests.get(current_url, headers=self.headers)
                
                if req.status_code != 200:
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {req.status_code}")
                    break
                    
                soup = BeautifulSoup(req.text, "html.parser")
                products = soup.find_all("li", class_="__list-item-base")
                
                if not products:
                    break
                    
                for p in products:
                    link_tag = p.find("a")
                    if link_tag and link_tag.get("href"):
                        product_url = base_url + link_tag.get("href")
                        links.append(product_url)
                        
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                pagination_links = soup.find_all("a", class_="__pagination-link")
                next_page = None
                
                for link in pagination_links:
                    if "__pagination-arrow-rotate-right" in link.get("class", []):
                        next_page = link.get("href")
                        break
                    elif link.text.strip() == str(page + 1):
                        next_page = link.get("href")
                        break
                
                if not next_page:
                    break
                    
                current_url = base_url + next_page
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                self.ui['status'].error(f"Error while fetching page {page}: {str(e)}")
                break
        
        total_products = len(links)
        processed = 0
        
        for link in links:
            if not self.running:
                break
                
            try:
                req = requests.get(link, headers=self.headers)
                soup = BeautifulSoup(req.text, "html.parser")
                title = soup.find("h1")
                title = title.text if title else "Unknown Title"
                
                sold_price = " "
                sold_price_tmp = soup.find_all("p", class_="text-gray-900 font-semibold line-clamp-1 text-label-sm xxs:text-title-xs xs:text-label-md sm:text-title-xs md:text-title-sm lg:text-title-md xl:text-title-sm xxl:text-title-xs")
                for x in sold_price_tmp:
                    if "$" in x.text:
                        sold_price = x.text
                        break
                
                if sold_price != " ":
                    retail_price = " "
                    retail_price_tmp = soup.find_all("div", class_="flex flex-col text-left")
                    for x in retail_price_tmp:
                        if "Estimated Retail Price" in x.text:
                            retail_price = x.text.replace("Estimated Retail Price", "").strip()
                            break
                        
                    if retail_price == " ":
                        retail_price_tmp = soup.find_all("div", class_="grid grid-cols-[minmax(0,_0.6fr)_minmax(0,_1fr)] gap-2 text-left")
                        for x in retail_price_tmp:
                            if "Estimated Retail Price" in x.text:
                                retail_price = x.text.replace("Estimated Retail Price", "").strip()
                                break 
                        
                    if retail_price != " ":
                        category = " "
                        category_tmp = soup.find("a", class_="flex items-center gap-1 text-secondary focus-within:outline-secondary hover:underline hover:text-secondary-light w-fit")
                        if category_tmp:
                            category = category_tmp.text.strip()
                            
                        self.process_item_no_ai(
                            title=title,
                            product_url=link,
                            sold_price_text=sold_price,
                            retail_price_text=retail_price,
                            item_index=processed + 1,
                            total_items_on_page=total_products,
                            category=category
                        )
                
                processed += 1
                time.sleep(0.1)
                
            except Exception as e:
                self.ui['status'].warning(f"Error processing product {processed+1}: {str(e)}")
                processed += 1

    def scrape_bidfta(self, url, start_page, end_page):
        """Scrape BidFTA - uses requests (no AI needed, has MSRP)"""
        base_url = "https://www.bidfta.com"
        current_url = url
        if not current_url.startswith("http"):
            current_url = f"https://{current_url}"
            
        urlz = current_url.split("/")
        if len(urlz) > 0 and urlz[-1].isdigit():
            del urlz[-1]
        current_url = "/".join(urlz)
        
        links = []
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                self.ui['status'].info(f"Fetching BidFTA page {page}...")
                page_url = f"{current_url}/{page}"
                req = requests.get(page_url, headers=self.headers)
                
                if req.status_code != 200:
                    break
                    
                soup = BeautifulSoup(req.text, "html.parser")
                div = soup.find("div", class_="grid grid-cols-1 gap-5 md:gap-6 pb-8 xl:pb-16 md:grid-cols-3 2xl:grid-cols-4")
                
                if not div:
                    break
                    
                products = div.find_all("div", class_="block")
                
                if not products:
                    break
                    
                new_links = 0
                for p in products:
                    link_tag = p.find("a")
                    if link_tag and link_tag.get("href"):
                        product_url = base_url + link_tag.get("href")
                        if product_url not in links:
                            links.append(product_url)
                            new_links += 1
                
                if new_links == 0:
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                self.ui['status'].error(f"Error while fetching page {page}: {str(e)}")
                break
        
        total_products = len(links)
        processed = 0
        
        for link in links:
            if not self.running:
                break
                
            try:
                req = requests.get(link, headers=self.headers)
                soup = BeautifulSoup(req.text, "html.parser")
                
                title_elem = soup.find("h2")
                title = title_elem.text.strip() if title_elem else "Unknown Title"
                
                sold_price = " "
                sold_price_elems = soup.find_all("div", class_="flex gap-1 xs:gap-2 items-end text-bidfta-blue-light")
                for elem in sold_price_elems:
                    if "CURRENT BID" in elem.text:
                        price_text = elem.text.replace("\n", "").replace("CURRENT BID", "").strip()
                        sold_price = re.sub(r"[^\d.]", "", price_text)
                        if sold_price.startswith("."):
                            sold_price = sold_price[1:]
                        if sold_price.endswith("."):
                            sold_price = sold_price[:-1]
                        break
                
                if sold_price != " ":
                    retail_price = " "
                    retail_price_elems = soup.find_all("div", class_="flex gap-1 xs:gap-2 items-end")
                    for elem in retail_price_elems:
                        if "MSRP" in elem.text:
                            price_text = elem.text.replace("MSRP", "").replace("\n", "").strip()
                            retail_price = re.sub(r"[^\d.]", "", price_text)
                            if retail_price.startswith("."):
                                retail_price = retail_price[1:]
                            if retail_price.endswith("."):
                                retail_price = retail_price[:-1]
                            break
                    
                    if retail_price != " ":
                        self.process_item_no_ai(
                            title=title,
                            product_url=link,
                            sold_price_text=sold_price,
                            retail_price_text=retail_price,
                            item_index=processed + 1,
                            total_items_on_page=total_products
                        )
                
                processed += 1
                time.sleep(0.1)
                
            except Exception as e:
                self.ui['status'].warning(f"Error processing product {processed+1}: {str(e)}")
                processed += 1

    def scrape_macbid(self, url, start_page, end_page):
        """Scrape MAC.bid - uses playwright (no AI needed, has retail prices)"""
        try:
            self.ui['status'].info("Starting MAC.bid scraper with browser...")
            
            current_url = url
            if not current_url.startswith("http"):
                current_url = f"https://{current_url}"
            
            self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
            base_url = "https://www.mac.bid"
            
            prev_product_count = 0
            page = start_page
            products_found = []
            
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            while self.running:
                self.ui['status'].info(f"Loading MAC.bid page {page}...")
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, 'html.parser')
                products = soup.find_all("div", class_="d-block w-100 border-bottom")
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                if len(products) != prev_product_count:
                    prev_product_count = len(products)
                    self.loop.run_until_complete(self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)'))
                    time.sleep(1)
                else:
                    if soup.find("div", class_="spinner-grow") is None:
                        products_found = products
                        break
                    else:
                        time.sleep(2)
            
            total_products = len(products_found)
            processed = 0
            
            for product in products_found:
                if not self.running:
                    break
                
                try:
                    if product.find("p", class_="badge badge-success") is not None:
                        title = product.find("p").text.strip()
                        sold_price = product.find("p", class_="badge badge-success").text.replace("Won for $", "").strip()
                        retail_price = product.find("p", class_="font-size-sm").text.replace("Retails for $", "").strip()
                        link_tag = product.find("a")
                        link = base_url + link_tag["href"] if link_tag and link_tag.get("href") else ""
                        
                        self.process_item_no_ai(
                            title=title,
                            product_url=link,
                            sold_price_text=sold_price,
                            retail_price_text=retail_price,
                            item_index=processed + 1,
                            total_items_on_page=total_products
                        )
                    
                    processed += 1
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.ui['status'].warning(f"Error processing product {processed+1}: {str(e)}")
                    processed += 1
                
        except Exception as e:
            self.ui['status'].error(f"Error in MAC.bid scraper: {str(e)}")

    def scrape_astock(self, url, start_page, end_page):
        """Scrape A-Stock.bid - uses requests (no AI needed, has retail prices)"""
        base_url = url.split("?")[0]
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                self.ui['status'].info(f"Fetching A-Stock page {page}...")
                current_url = f"{base_url}?page={page}"
                
                response = requests.get(current_url, headers=self.headers)
                if response.status_code != 200:
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {response.status_code}")
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                sections = soup.find_all("section")
                
                if len(sections) == 0:
                    self.ui['status'].success("No items found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                total_sections = len(sections)
                self.ui['status'].info(f"Found {total_sections} items on page {page}")
                
                for i, section in enumerate(sections, 1):
                    if not self.running:
                        break
                        
                    try:
                        title_elem = section.find("h2", class_="title inlinebidding")
                        if not title_elem:
                            continue
                            
                        linker = section.find("h2", class_="title inlinebidding").find("a")
                        if linker:
                            linker = "https://a-stock.bid" + linker.get("href")
                        else:
                            linker = "N/A"
                        
                        if "-" in title_elem.text:
                            title = title_elem.text.split("-", 1)[1].lstrip().rstrip()
                        else:
                            title = title_elem.text.strip()
                        
                        sold_price_elem = section.find("p", class_="bids")
                        if not sold_price_elem:
                            continue
                            
                        sold_price_text = sold_price_elem.text.strip()
                        sold_price = re.sub(r"[^\d.]", "", sold_price_text)
                        
                        try:
                            sold_price_float = float(sold_price)
                        except ValueError:
                            continue
                        
                        retail_price_elem = section.find("div", class_="listing-auction-row-retail-value")
                        if not retail_price_elem:
                            continue
                            
                        retail_price_text = retail_price_elem.text.strip()
                        retail_price = re.sub(r"[^\d.]", "", retail_price_text)
                        
                        try:
                            retail_price_float = float(retail_price)
                        except ValueError:
                            continue
                        
                        self.process_item_no_ai(
                            title=title,
                            product_url=linker,
                            sold_price_text=str(sold_price_float),
                            retail_price_text=str(retail_price_float),
                            item_index=i,
                            total_items_on_page=total_sections
                        )
                        
                    except Exception as e:
                        self.ui['status'].warning(f"Error processing item {i}: {str(e)}")
                        continue
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                self.ui['status'].error(f"Error fetching page {page}: {str(e)}")
                break

    def scrape_702auctions(self, url, start_page, end_page):
        """Scrape 702Auctions - uses requests"""
        auction_base_url = "https://bid.702auctions.com"
        
        base_url = url
        if "ViewStyle=list" not in url:
            temp_url = base_url.replace("https://", "")
            temp_url = temp_url.split("/")
            del temp_url[-1]
            temp_url = "/".join(temp_url)
            base_url = "https://" + temp_url
        
        page = start_page - 1 if start_page > 0 else 0
        
        while self.running and (end_page == 0 or page < end_page):
            try:
                self.ui['status'].info(f"Fetching 702Auctions page {page}...")
                current_url = f"{base_url}/?ViewStyle=list&StatusFilter=completed_only&SortFilterOptions=0&page={page}"
                
                response = requests.get(current_url, headers=self.headers)
                if response.status_code != 200:
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {response.status_code}")
                    break
                    
                soup = BeautifulSoup(response.text, "html.parser")
                sections = soup.find_all("section")
                
                if not sections:
                    self.ui['status'].success("No more items found on this page. Ending scrape.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page + 1)
                
                total_sections = len(sections)
                self.ui['status'].info(f"Found {total_sections} items on page {page}")
                
                for i, section in enumerate(sections, 1):
                    if not self.running:
                        break
                        
                    try:
                        title_elem = section.find("h2", class_="title inlinebidding")
                        if not title_elem:
                            continue
                            
                        linker = section.find("h3", class_="subtitle")
                        if linker:
                            linker = linker.find("a")
                            if linker:
                                link_href = linker.get("href")
                                if link_href and not link_href.startswith("http"):
                                    linker = auction_base_url + link_href
                                else:
                                    linker = link_href if link_href else "N/A"
                            else:
                                linker = "N/A"
                        else:
                            linker = "N/A"
                        
                        if "-" in title_elem.text:
                            title = title_elem.text.split("-", 1)[1].lstrip().rstrip()
                        else:
                            title = title_elem.text.strip()
                        
                        sold_price_elem = section.find("span", class_="NumberPart")
                        if not sold_price_elem:
                            continue
                            
                        sold_price_text = sold_price_elem.text.strip()
                        sold_price_match = re.search(r'\$?([\d,]+\.?\d*)', sold_price_text)
                        if sold_price_match:
                            sold_price_str = sold_price_match.group(1).replace(',', '')
                            sold_price_float = float(sold_price_str)
                        else:
                            continue

                        retail_price_elem = section.find("h3", class_="subtitle")
                        if not retail_price_elem:
                            continue
                            
                        retail_price_text = retail_price_elem.text.strip()
                        retail_price_match = re.search(r'\$?([\d,]+\.?\d*)', retail_price_text)
                        if retail_price_match:
                            retail_price_str = retail_price_match.group(1).replace(',', '')
                            retail_price_float = float(retail_price_str)
                        else:
                            continue
                        
                        self.process_item_no_ai(
                            title=title,
                            product_url=linker,
                            sold_price_text=str(sold_price_float),
                            retail_price_text=str(retail_price_float),
                            item_index=i,
                            total_items_on_page=total_sections
                        )
                        
                    except Exception as e:
                        continue
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                self.ui['status'].error(f"Error fetching page {page}: {str(e)}")
                break

    def scrape_vista(self, url, start_page, end_page):
        """Scrape Vista Auction - uses playwright"""
        base_url = url.split("?")[0]
        vista_base_url = "https://vistaauction.com"
        page = start_page - 1 if start_page > 0 else 0
        
        while self.running and (end_page == 0 or page < end_page):
            try:
                current_url = f"{base_url}?page={page}"
                self.ui['status'].info(f"Fetching Vista Auction page {page}...")
                
                self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
                time.sleep(5)
                
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, "html.parser")
                sections = soup.find_all("section")
                
                if not sections:
                    self.ui['status'].success("No more items found on this page. Ending scrape.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page + 1)
                
                total_sections = len(sections)
                self.ui['status'].info(f"Found {total_sections} items on page {page}")
                
                for i, section in enumerate(sections, 1):
                    if not self.running:
                        break
                        
                    try:
                        title_elem = section.find("h2", class_="title inlinebidding")
                        if title_elem:
                            raw_title = title_elem.text.strip()
                            title = re.sub(r'^Lot \d+\s*-\s*', '', raw_title).strip()
                        else:
                            continue

                        linker_elem = section.find("h3", class_="subtitle")
                        linker = "N/A"
                        if linker_elem:
                            link_tag = linker_elem.find("a")
                            if link_tag:
                                link_href = link_tag.get("href")
                                if link_href and not link_href.startswith("http"):
                                    linker = vista_base_url + link_href
                                else:
                                    linker = link_href if link_href else "N/A"

                        sold_price_elem = section.find("span", class_="NumberPart")
                        if not sold_price_elem:
                            continue
                            
                        sold_price_text = sold_price_elem.text.strip()
                        sold_price_match = re.search(r'\$?([\d,]+\.?\d*)', sold_price_text)
                        if sold_price_match:
                            sold_price_str = sold_price_match.group(1).replace(',', '')
                            sold_price_float = float(sold_price_str)
                        else:
                            continue
                        
                        retail_price_elem = section.find("h3", class_="subtitle")
                        if not retail_price_elem:
                            continue

                        retail_price_text = retail_price_elem.text.strip()
                        retail_price_match = re.search(r'\$?([\d,]+\.?\d*)', retail_price_text)
                        if retail_price_match:
                            retail_price_str = retail_price_match.group(1).replace(',', '')
                            retail_price_float = float(retail_price_str)
                        else:
                            continue
                        
                        self.process_item_no_ai(
                            title=title,
                            product_url=linker,
                            sold_price_text=str(sold_price_float),
                            retail_price_text=str(retail_price_float),
                            item_index=i,
                            total_items_on_page=total_sections
                        )
                        
                    except Exception as e:
                        continue
                
                page += 1
                
            except Exception as e:
                self.ui['status'].error(f"Error fetching page {page}: {str(e)}")
                break

    def scrape_bidsoflo(self, url, start_page, end_page):
        """Scrape BidSoflo - uses playwright (no AI needed, has retail prices)"""
        base_url = "https://bid.bidsoflo.us"
        current_url = url
        page = start_page
        
        self.ui['status'].info("Starting BidSoflo scraper...")
        self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
        time.sleep(2)
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                page_flag = False
                self.ui['status'].info(f"Fetching BidSoflo page {page}")
                
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, 'html.parser')
                
                products = soup.find_all("div", class_="row mr-1")
                
                tmp_page = soup.find_all("li", class_="page-item")
                for pa in tmp_page:
                    if "next" in pa.text.lower():
                        urlz = pa.find("a", class_="page-link")
                        if urlz is not None:
                            urlz = urlz["data-url"].split("page=")[-1]
                            t_url = current_url.split("=")[-1]
                            current_url = current_url.replace(t_url, urlz)
                            page_flag = True
                        else:
                            page_flag = False
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                total_products = len(products)
                self.ui['status'].info(f"Found {total_products} items on page {page}")
                
                product_count = 0
                for i, p in enumerate(products, 1):
                    if not self.running:
                        break
                        
                    try:
                        if p.find("div", class_="tooltip-demos") is not None:
                            tool = p.find("div", class_="tooltip-demos")
                            tmp = tool.find_all("div", recursive=False)
                            
                            title = " "
                            for xi in tmp:
                                if "Item Description" in xi.text:
                                    title = xi.text.replace("Item Description", "").strip()
                                    break
                                    
                            if title != " ":
                                retail_price = " "
                                for xi in tmp:
                                    if "Retail Cost:" in xi.text:
                                        retail_price = xi.text.replace("Retail Cost:", "").replace("$", "").strip()
                                        break
                                
                                if retail_price != " ":
                                    sold_price = " "
                                    tmp_price = p.find("div", class_="font-bold text-body")
                                    if tmp_price is not None:
                                        if "Final Bid :" in tmp_price.text:
                                            sold_price = tmp_price.text.replace("Final Bid :", "").replace("$", "").strip()
                                            
                                            if sold_price != " ":
                                                try:
                                                    sold_price_float = float(sold_price.replace("$", "").replace(",", ""))
                                                    retail_price_float = float(retail_price.replace("$", "").replace(",", ""))
                                                except (ValueError, ZeroDivisionError):
                                                    continue
                                                
                                                link_tag = p.find("a")
                                                link = base_url + link_tag["href"] if link_tag and link_tag.get("href") else "N/A"
                                                
                                                self.process_item_no_ai(
                                                    title=title,
                                                    product_url=link,
                                                    sold_price_text=str(sold_price_float),
                                                    retail_price_text=str(retail_price_float),
                                                    item_index=product_count + 1,
                                                    total_items_on_page=total_products
                                                )
                                                
                                                product_count += 1
                    
                    except Exception as e:
                        self.ui['status'].warning(f"Error processing item {i}: {str(e)}")
                        continue
                
                self.ui['status'].info(f"Processed {product_count} valid items on page {page}")
                
                if page_flag:
                    self.ui['status'].info(f"Moving to page {page+1}...")
                    self.loop.run_until_complete(self.page.goto(current_url, wait_until='networkidle', timeout=60000))
                    page += 1
                    time.sleep(2)
                else:
                    self.ui['status'].success("No more pages to fetch.")
                    break
                    
            except Exception as e:
                self.ui['status'].error(f"Error on page {page}: {str(e)}")
                break

    def scrape_bidauctiondepot(self, url, start_page, end_page):
        """Scrape BidAuctionDepot - uses playwright (no AI needed, has retail prices)"""
        base_url = "https://bidauctiondepot.com/productView/"
        page = start_page
        lot_id = ""
        flag = True
        
        self.ui['status'].info("Starting BidAuctionDepot scraper...")
        self.loop.run_until_complete(self.page.goto(url, wait_until='networkidle', timeout=60000))
        time.sleep(3)
        
        while self.running and flag and (end_page == 0 or page <= end_page):
            try:
                self.ui['status'].info(f"Fetching BidAuctionDepot page {page}")
                
                try:
                    self.loop.run_until_complete(self.page.wait_for_selector('div[class^="card grid-card a gallery auction"]', timeout=25000))
                    self.ui['status'].info("Product cards loaded successfully")
                except Exception as e:
                    self.ui['status'].error(f"Error waiting for products: {str(e)}")
                            
                html = self.loop.run_until_complete(self.page.content())
                soup = BeautifulSoup(html, 'html.parser')
                
                products = soup.find_all('div', class_=lambda c: c and "card grid-card a gallery auction" in c)
                
                if not products:
                    self.ui['status'].success("No products found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                total_products = len(products)
                self.ui['status'].info(f"Found {total_products} items on page {page}")
                
                for i, p in enumerate(products, 1):
                    if not self.running:
                        break
                        
                    try:
                        title_elem = p.find("h5")
                        if not title_elem:
                            continue
                            
                        title = title_elem.text.strip()
                        
                        retail_price_elem = p.select_one("h6.galleryPrice.rtlrPrice")
                        if not retail_price_elem:
                            continue
                            
                        retail_price_text = retail_price_elem.text.replace("Retail Price:", "").replace("$", "").replace(",", "").strip()
                        
                        try:
                            retail_price_float = float(retail_price_text)
                        except ValueError:
                            continue
                        
                        sold_price_elem = p.find("span", class_="curBidAmtt")
                        if not sold_price_elem:
                            continue
                            
                        sold_price_text = sold_price_elem.text.replace("Current Bid:", "").replace("$", "").replace(",", "").strip()
                        
                        try:
                            sold_price_float = float(sold_price_text)
                        except ValueError:
                            continue
                        
                        link_elem = p.get("id")
                        if not link_elem:
                            continue
                            
                        link_id = link_elem.replace("lot-", "")
                        
                        if lot_id == link_id:
                            self.ui['status'].warning("Duplicate lot found. Ending scrape.")
                            flag = False
                            break
                        else:
                            lot_id = link_id
                        
                        link = base_url + link_id
                        
                        self.process_item_no_ai(
                            title=title,
                            product_url=link,
                            sold_price_text=str(sold_price_float),
                            retail_price_text=str(retail_price_float),
                            item_index=i,
                            total_items_on_page=total_products
                        )
                        
                    except Exception as e:
                        self.ui['status'].warning(f"Error processing item {i}: {str(e)}")
                        continue
                
                if not flag:
                    break
                
                try:
                    next_button_exists = self.loop.run_until_complete(
                        self.page.evaluate('() => document.querySelector("a[aria-label=\'Go to next page\']") !== null')
                    )
                    
                    if next_button_exists:
                        self.loop.run_until_complete(
                            self.page.evaluate('() => document.querySelector("a[aria-label=\'Go to next page\']").click()')
                        )
                        page += 1
                        time.sleep(3)
                        self.ui['status'].info(f"Navigating to page {page}")
                    else:
                        self.ui['status'].success("No more pages to scrape.")
                        break
                except Exception as e:
                    self.ui['status'].warning("Error during pagination, stopping scraper.")
                    break
                    
            except Exception as e:
                self.ui['status'].error(f"Error on page {page}: {str(e)}")
                break
