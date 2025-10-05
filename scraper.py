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

# Check if we're running in Streamlit Cloud (disable Selenium features)
IS_CLOUD = os.getenv('STREAMLIT_SHARING_MODE') or os.getenv('STREAMLIT_RUNTIME_ENV') == 'cloud'

if not IS_CLOUD:
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, NoSuchElementException
        SELENIUM_AVAILABLE = True
        print("✅ Selenium loaded successfully - browser scrapers enabled")
    except ImportError as e:
        SELENIUM_AVAILABLE = False
        print(f"❌ Selenium not available: {e}")
else:
    SELENIUM_AVAILABLE = False
    print("☁️ Running in cloud mode - browser-based scrapers disabled")

class AuctionScraper:
    def __init__(self, gemini_api_keys, ui_placeholders):
        print("\n" + "="*60)
        print("INITIALIZING AUCTION SCRAPER")
        print("="*60)
        
        self.running = True
        self._is_running = True
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.products = []
        self.percentages = []
        self.ui = ui_placeholders
        self.gemini_api_keys = [key for key in gemini_api_keys if key]
        self.current_api_key_index = 0
        self.gemini_client = None
        
        # Selenium driver (only if available)
        self.driver = None
        
        # Rate limiting variables
        self.request_times = []
        self.max_requests_per_minute = 10
        
        print(f"Gemini API Keys Available: {len(self.gemini_api_keys)}")
        print(f"Selenium Available: {SELENIUM_AVAILABLE}")
        print(f"Cloud Mode: {IS_CLOUD}")
        
        if self.gemini_api_keys:
            self.setup_gemini()
        
        print("="*60 + "\n")

    def stop(self):
        print("\nSTOP SIGNAL RECEIVED")
        self.running = False
        self._is_running = False
        if self.driver and SELENIUM_AVAILABLE:
            try:
                print("Closing browser...")
                self.driver.quit()
                print("Browser closed")
            except Exception as e:
                print(f"Error closing browser: {e}")

    def setup_gemini(self):
        print("\nSetting up Gemini AI...")
        try:
            if not self.gemini_api_keys:
                print("No Gemini API keys found")
                self.ui['status'].warning("No Gemini API keys found.")
                return

            api_key = self.gemini_api_keys[self.current_api_key_index]
            print(f"Using API Key #{self.current_api_key_index + 1}")
            self.gemini_client = genai.Client(api_key=api_key)
            print("Gemini AI initialized successfully")
            self.ui['status'].info(f"AI price lookup enabled with Gemini Client (API Key {self.current_api_key_index + 1})")

        except Exception as e:
            print(f"Failed to setup Gemini: {e}")
            traceback.print_exc()
            self.ui['status'].error(f"An unexpected error occurred setting up Gemini AI: {e}.")
            self.gemini_client = None

    def init_driver(self):
        """Initialize undetected Chrome driver - only works locally"""
        print("\nInitializing browser driver...")
        
        if not SELENIUM_AVAILABLE:
            print("Selenium not available")
            self.ui['status'].error("Browser automation not available in cloud deployment.")
            return False
            
        try:
            print("Configuring Chrome options...")
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            print("Launching Chrome browser...")
            self.driver = uc.Chrome(options=options, version_main=None)
            self.driver.set_page_load_timeout(60)
            print("Browser initialized successfully")
            self.ui['status'].info("Browser initialized successfully")
            return True
        except Exception as e:
            print(f"Browser initialization failed: {e}")
            traceback.print_exc()
            self.ui['status'].error(f"Failed to initialize browser: {e}")
            return False

    def can_make_request(self):
        now = datetime.now()
        self.request_times = [req_time for req_time in self.request_times if now - req_time < timedelta(minutes=1)]
        return len(self.request_times) < self.max_requests_per_minute

    def wait_for_rate_limit(self):
        while not self.can_make_request():
            if self.request_times:
                oldest_request = min(self.request_times)
                wait_time = 60 - (datetime.now() - oldest_request).total_seconds()
                if wait_time > 0:
                    print(f"Waiting {wait_time:.0f}s for rate limit...")
                    self.ui['status'].info(f"Rate limit reached. Waiting {wait_time:.0f} seconds...")
                    time.sleep(max(1, wait_time))
            else:
                break

    def record_request(self):
        self.request_times.append(datetime.now())

    def get_retail_price(self, product_name, image_url):
        print(f"\nGetting retail price for: {product_name[:50]}...")
        
        if not self.gemini_client:
            print("Gemini client not initialized")
            return None
            
        for attempt in range(len(self.gemini_api_keys)):
            try:
                self.wait_for_rate_limit()
                
                print(f"Downloading image from: {image_url[:60]}...")
                response = requests.get(image_url, headers=self.headers, stream=True, timeout=15)
                if response.status_code != 200:
                    print(f"Failed to download image: HTTP {response.status_code}")
                    return None
                
                image_bytes = response.content
                print(f"Image downloaded: {len(image_bytes)} bytes")
                
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
                
                print("Sending request to Gemini AI...")
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents
                )

                response_text = response.text.strip()
                print(f"AI Response: {response_text}")
                
                match = re.search(r'([\d,]+\.?\d*)\s*,\s*(https?://\S+)', response_text)
                if match:
                    price = match.group(1).replace(',', '')
                    link = match.group(2)
                    print(f"Price found: ${price}")
                    return f"{price}, {link}"
                else:
                    print(f"AI response format invalid")
                    raise ValueError("Invalid AI response format")

            except Exception as e:
                error_str = str(e)
                print(f"Error getting price: {error_str}")
                
                if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
                    print("Rate limit hit! Waiting 30 seconds...")
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
                        print(f"Retry failed: {retry_e}")
                        self.ui['status'].warning(f"Retry failed: {retry_e}")
                
                traceback.print_exc()
                
                self.current_api_key_index = (self.current_api_key_index + 1) % len(self.gemini_api_keys)
                print(f"Switching to API Key #{self.current_api_key_index + 1}")
                self.ui['status'].warning(f"Switching to Gemini API Key {self.current_api_key_index + 1} due to error.")
                self.setup_gemini()
                self.request_times = []
        
        print("All Gemini API keys exhausted")
        self.ui['status'].error("All Gemini API keys failed. Disabling AI for this session.")
        self.gemini_client = None
        return None

    def run(self, site, url, start_page, end_page):
        print("\n" + "="*60)
        print(f"STARTING SCRAPER: {site}")
        print("="*60)
        print(f"URL: {url}")
        print(f"Pages: {start_page} to {end_page if end_page > 0 else 'unlimited'}")
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60 + "\n")
        
        try:
            selenium_sites = ["HiBid", "BiddingKings", "BidLlama", "MAC.bid", "Vista", "BidAuctionDepot", "BidSoflo"]
            
            if site in selenium_sites:
                print(f"{site} requires browser automation")
                
                if not SELENIUM_AVAILABLE:
                    print(f"Selenium not available for {site}")
                    self.ui['status'].error(f"{site} requires browser automation which is not available in cloud deployment.")
                    self.ui['status'].info("This scraper only works in local deployment. Please use direct price scrapers instead:")
                    self.ui['status'].info("Nellis, BidFTA, A-Stock, 702Auctions")
                    return []
                
                print(f"Initializing browser for {site}...")
                if not self.init_driver():
                    print("Browser initialization failed")
                    return []
                
                print(f"Browser ready, starting {site} scraper...")
                
                if site == "HiBid": 
                    self.scrape_hibid(url, start_page, end_page)
                elif site == "BiddingKings": 
                    self.scrape_biddingkings(url, start_page, end_page)
                elif site == "BidLlama": 
                    self.scrape_bidllama(url, start_page, end_page)
                elif site == "MAC.bid": 
                    self.scrape_macbid(url, start_page, end_page)
                elif site == "Vista":
                    self.scrape_vista(url, start_page, end_page)
                elif site == "BidSoflo":
                    self.scrape_bidsoflo(url, start_page, end_page)
                elif site == "BidAuctionDepot":
                    self.scrape_bidauctiondepot(url, start_page, end_page)
            else:
                print(f"{site} uses direct HTTP requests (no browser needed)")
                
                if site == "Nellis": 
                    self.scrape_nellis(url, start_page, end_page)
                elif site == "BidFTA": 
                    self.scrape_bidfta(url, start_page, end_page)
                elif site == "A-Stock":
                    self.scrape_astock(url, start_page, end_page)
                elif site == "702Auctions":
                    self.scrape_702auctions(url, start_page, end_page)
                    
        except Exception as e:
            print(f"\nCRITICAL ERROR in run(): {e}")
            traceback.print_exc()
            self.ui['status'].error(f"An unexpected error occurred during scraping: {e}")
        finally:
            if self.driver and SELENIUM_AVAILABLE:
                try:
                    print("\nCleaning up browser...")
                    self.driver.quit()
                    print("Browser closed")
                except Exception as e:
                    print(f"Error during cleanup: {e}")
        
        print("\n" + "="*60)
        print(f"SCRAPING COMPLETE: {site}")
        print(f"Total products scraped: {len(self.products)}")
        print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60 + "\n")
        
        return self.products

    def process_item(self, title, product_url, image_url, sold_price_text, item_index, total_items_on_page, category=None):
        print(f"\nProcessing item {item_index}/{total_items_on_page}")
        print(f"Title: {title[:60]}...")
        
        try:
            self.ui['status'].info(f"Processing item {item_index}/{total_items_on_page}: {title[:40]}...")
            sold_price_float = round(float(sold_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            print(f"Sold Price: ${sold_price_float}")
            
            ai_result = self.get_retail_price(title, image_url)
            if ai_result:
                price_part, link_part = ai_result.split(',', 1)
                retail_price_float = round(float(price_part.strip().replace('$', '')), 2)
                print(f"Retail Price: ${retail_price_float}")
                
                if retail_price_float > 0:
                    percentage = round((sold_price_float / retail_price_float) * 100, 2)
                    print(f"Recovery: {percentage:.1f}%")
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
                    print(f"Item added to results (Total: {len(self.products)})")
                    
                    df = pd.DataFrame(self.products)
                    self.ui['dataframe'].dataframe(df, use_container_width=True)
                    
                    avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
                    self.ui['metrics']['lots'].metric("Lots Scraped", len(self.products))
                    self.ui['metrics']['recovery'].metric("Average Recovery", f"{avg_recovery:.1f}%")
                    self.ui['progress'].progress(item_index / total_items_on_page, text=f"Page Progress: {item_index}/{total_items_on_page}")
            else:
                print(f"Skipping item - AI could not find retail price")
                self.ui['status'].warning(f"Skipping '{title[:30]}...' - AI could not find a retail price.")
        except Exception as e:
            print(f"Error processing item: {e}")
            traceback.print_exc()
            self.ui['status'].warning(f"Skipping item '{title[:30]}...' due to error: {e}")

    def process_item_no_ai(self, title, product_url, sold_price_text, retail_price_text, item_index, total_items_on_page, category=None):
        print(f"\nProcessing item {item_index}/{total_items_on_page} (No AI)")
        print(f"Title: {title[:60]}...")
        
        try:
            self.ui['status'].info(f"Processing item {item_index}/{total_items_on_page}: {title[:40]}...")
            sold_price_float = round(float(sold_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            retail_price_float = round(float(retail_price_text.replace("$", "").replace("USD", "").replace(",", "").strip()), 2)
            
            print(f"Sold: ${sold_price_float}, Retail: ${retail_price_float}")
            
            if retail_price_float > 0:
                percentage = round((sold_price_float / retail_price_float) * 100, 2)
                print(f"Recovery: {percentage:.1f}%")
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
                print(f"Item added (Total: {len(self.products)})")
                
                df = pd.DataFrame(self.products)
                self.ui['dataframe'].dataframe(df, use_container_width=True)
                
                avg_recovery = statistics.mean(self.percentages) if self.percentages else 0
                self.ui['metrics']['lots'].metric("Lots Scraped", len(self.products))
                self.ui['metrics']['recovery'].metric("Average Recovery", f"{avg_recovery:.1f}%")
                self.ui['progress'].progress(item_index / total_items_on_page, text=f"Page Progress: {item_index}/{total_items_on_page}")
        except Exception as e:
            print(f"Error processing item: {e}")
            traceback.print_exc()
            self.ui['status'].warning(f"Skipping item '{title[:30]}...' due to error: {e}")

    # === SELENIUM-BASED SCRAPERS ===
    
    def scrape_hibid(self, url, start_page, end_page):
        print(f"\nStarting HiBid scraper")
        base_url = url.split("/catalog")[0]
        print(f"Base URL: {base_url}")
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                print(f"\nNavigating to HiBid Page: {page}")
                current_url = f"{url}{'&' if '?' in url else '?'}apage={page}"
                print(f"Full URL: {current_url}")
                
                self.ui['status'].info(f"Navigating to HiBid Page: {page}...")
                self.driver.get(current_url)
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                try:
                    print("Waiting for products to load...")
                    WebDriverWait(self.driver, 40).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "h2.lot-title"))
                    )
                    print("Products loaded")
                except TimeoutException:
                    print("Timeout - no products found")
                    self.ui['status'].success("No more pages found. Scraping complete.")
                    break
                
                time.sleep(2)
                html = self.driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                
                products = [p for p in soup.find_all("app-lot-tile") if p.find("strong", class_="lot-price-realized")]
                print(f"Found {len(products)} products on page {page}")
                
                if not products:
                    print("No products with prices found")
                    self.ui['status'].success("No more items with prices on this page. Scraping complete.")
                    break

                for i, p in enumerate(products, 1):
                    if not self.running: 
                        print("Stop signal detected")
                        break
                    
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
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                traceback.print_exc()
                self.ui['status'].error(f"Error on page {page}: {str(e)}")
                break

    def scrape_biddingkings(self, url, start_page, end_page):
        print(f"\nStarting BiddingKings scraper")
        base_url = "https://auctions.biddingkings.com"
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                current_url = f"{url}?page={page}"
                print(f"\nNavigating to BiddingKings Page: {page}")
                print(f"URL: {current_url}")
                
                self.ui['status'].info(f"Scraping BiddingKings Page: {page}")
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                self.driver.get(current_url)
                time.sleep(3)
                
                try:
                    print("Waiting for products...")
                    WebDriverWait(self.driver, 40).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='lot-repeater-index']"))
                    )
                    print("Products loaded")
                except TimeoutException:
                    print("Timeout - no products")
                    self.ui['status'].success("No more pages found. Scraping complete.")
                    break
                
                html = self.driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                products = soup.find_all("div", class_=re.compile(r'lot-repeater-index'))
                print(f"Found {len(products)} products")
                
                if not products:
                    print("No products found")
                    self.ui['status'].success("No more items. Scraping complete.")
                    break
                    
                for i, p in enumerate(products, 1):
                    if not self.running: break
                    
                    link_tag = p.find("a")
                    img_tag = p.find("img")
                    
                    if link_tag and img_tag:
                        title = link_tag.text.strip()
                        product_url = base_url + link_tag.get("href")
                        
                        print(f"Navigating to product page: {product_url}")
                        self.driver.get(product_url)
                        time.sleep(2)
                        
                        product_html = self.driver.page_source
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
                        
                        print("Going back to listing page")
                        self.driver.back()
                        time.sleep(1)
                    
                    time.sleep(0.5)
                
                page += 1
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                traceback.print_exc()
                break

    def generate_next_bidllama_urls(self, original_url, total_pages=500):
        if "#" not in original_url: return [original_url]
        base_url, encoded_fragment = original_url.split("#", 1)
        padding = "=" * (4 - len(encoded_fragment) % 4)
        try:
            import base64
            decoded = base64.b64decode(encoded_fragment + padding).decode()
            current_page = int(re.search(r'page=(\d+)', decoded).group(1))
            urls = []
            for page_num in range(current_page, current_page + total_pages):
                new_decoded = re.sub(r'page=\d+', f'page={page_num}', decoded)
                new_encoded = base64.b64encode(new_decoded.encode()).decode().rstrip("=")
                urls.append(base_url + "#" + new_encoded)
            return urls
        except Exception:
            return [original_url]

    def scrape_bidllama(self, url, start_page, end_page):
        print(f"\nStarting BidLlama scraper")
        base_url = "https://bid.bidllama.com"
        page = start_page
        paginated_urls = self.generate_next_bidllama_urls(url)
        print(f"Generated {len(paginated_urls)} URLs")
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                if page - 1 >= len(paginated_urls):
                    print("Reached end of generated URLs")
                    self.ui['status'].success("Reached end of generated URLs.")
                    break
                    
                current_url = paginated_urls[page-1]
                print(f"\nNavigating to BidLlama Page: {page}")
                print(f"URL: {current_url[:80]}...")
                
                self.ui['status'].info(f"Scraping BidLlama Page: {page}")
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
                self.driver.get(current_url)
                time.sleep(5)
                
                try:
                    print("Waiting for products...")
                    WebDriverWait(self.driver, 40).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "p.item-lot-number"))
                    )
                    print("Products loaded")
                except TimeoutException:
                    print("Timeout - no products")
                    self.ui['status'].success("No more pages found. Scraping complete.")
                    break
                
                html = self.driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                item_container = soup.find("div", class_="item-row grid")
                
                if not item_container:
                    print("No item container found")
                    self.ui['status'].success("No item container found on page. Scraping complete.")
                    break
                
                products = item_container.find_all("div", recursive=False)
                print(f"Found {len(products)} products")
                
                if not products:
                    print("No products found")
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
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                traceback.print_exc()
                break



    def scrape_macbid(self, url, start_page, end_page):
        print(f"\nStarting MAC.bid scraper")
        current_url = url
        if not current_url.startswith("http"):
            current_url = f"https://{current_url}"
        
        print(f"Navigating to: {current_url}")
        self.driver.get(current_url)
        base_url = "https://www.mac.bid"
        
        prev_product_count = 0
        page = start_page
        products_found = []
        
        self.ui['metrics']['pages'].metric("Pages Scraped", page)
        
        print("Scrolling to load all products...")
        while self.running:
            self.ui['status'].info(f"Loading MAC.bid page {page}...")
            
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            products = soup.find_all("div", class_="d-block w-100 border-bottom")
            
            print(f"Current product count: {len(products)}")
            self.ui['metrics']['pages'].metric("Pages Scraped", page)
            
            if len(products) != prev_product_count:
                prev_product_count = len(products)
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            else:
                if soup.find("div", class_="spinner-grow") is None:
                    products_found = products
                    print(f"All products loaded: {len(products_found)}")
                    break
                else:
                    print("Still loading...")
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
                print(f"Error processing product {processed+1}: {e}")
                self.ui['status'].warning(f"Error processing product {processed+1}: {str(e)}")
                processed += 1

    def scrape_vista(self, url, start_page, end_page):
        print(f"\nStarting Vista scraper")
        base_url = url.split("?")[0]
        vista_base_url = "https://vistaauction.com"
        page = start_page - 1 if start_page > 0 else 0
        
        while self.running and (end_page == 0 or page < end_page):
            try:
                current_url = f"{base_url}?page={page}"
                print(f"\nNavigating to Vista page: {page}")
                print(f"URL: {current_url}")
                
                self.ui['status'].info(f"Fetching Vista Auction page {page}...")
                self.driver.get(current_url)
                time.sleep(5)
                
                html = self.driver.page_source
                soup = BeautifulSoup(html, "html.parser")
                sections = soup.find_all("section")
                print(f"Found {len(sections)} sections")
                
                if not sections:
                    print("No sections found")
                    self.ui['status'].success("No more items found on this page. Ending scrape.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page + 1)
                
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
                            total_items_on_page=len(sections)
                        )
                        
                    except Exception as e:
                        continue
                
                page += 1
                
            except Exception as e:
                print(f"Error fetching page {page}: {e}")
                traceback.print_exc()
                break

    def scrape_bidsoflo(self, url, start_page, end_page):
        print(f"\nStarting BidSoflo scraper")
        base_url = "https://bid.bidsoflo.us"
        current_url = url
        page = start_page
        
        print(f"Navigating to: {current_url}")
        self.driver.get(current_url)
        time.sleep(2)
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                page_flag = False
                print(f"\nFetching BidSoflo page {page}")
                
                html = self.driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                
                products = soup.find_all("div", class_="row mr-1")
                print(f"Found {len(products)} products")
                
                tmp_page = soup.find_all("li", class_="page-item")
                for pa in tmp_page:
                    if "next" in pa.text.lower():
                        urlz = pa.find("a", class_="page-link")
                        if urlz is not None:
                            urlz = urlz["data-url"].split("page=")[-1]
                            t_url = current_url.split("=")[-1]
                            current_url = current_url.replace(t_url, urlz)
                            page_flag = True
                            print(f"Next page found: {current_url}")
                        else:
                            page_flag = False
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
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
                                                    total_items_on_page=len(products)
                                                )
                                                
                                                product_count += 1
                    
                    except Exception as e:
                        print(f"Error processing item {i}: {e}")
                        continue
                
                print(f"Processed {product_count} valid items on page {page}")
                
                if page_flag:
                    print(f"Moving to page {page+1}...")
                    self.driver.get(current_url)
                    page += 1
                    time.sleep(2)
                else:
                    print("No more pages")
                    self.ui['status'].success("No more pages to fetch.")
                    break
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                traceback.print_exc()
                break

    def scrape_bidauctiondepot(self, url, start_page, end_page):
        print(f"\nStarting BidAuctionDepot scraper")
        base_url = "https://bidauctiondepot.com/productView/"
        page = start_page
        lot_id = ""
        flag = True
        
        print(f"Navigating to: {url}")
        self.driver.get(url)
        time.sleep(3)
        
        while self.running and flag and (end_page == 0 or page <= end_page):
            try:
                print(f"\nFetching BidAuctionDepot page {page}")
                
                try:
                    print("Waiting for product cards...")
                    WebDriverWait(self.driver, 25).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class*="card grid-card a gallery auction"]'))
                    )
                    print("Product cards loaded")
                except TimeoutException:
                    print("Timeout waiting for products")
                
                html = self.driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                
                products = soup.find_all('div', class_=lambda c: c and "card grid-card a gallery auction" in c)
                print(f"Found {len(products)} products")
                
                if not products:
                    print("No products found")
                    self.ui['status'].success("No products found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
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
                            print("Duplicate lot found, ending scrape")
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
                            total_items_on_page=len(products)
                        )
                        
                    except Exception as e:
                        print(f"Error processing item {i}: {e}")
                        continue
                
                if not flag:
                    break
                
                try:
                    print("Looking for next page button...")
                    next_button = self.driver.find_element(By.CSS_SELECTOR, "a[aria-label='Go to next page']")
                    if next_button:
                        print("Clicking next page")
                        next_button.click()
                        page += 1
                        time.sleep(3)
                    else:
                        print("No more pages")
                        break
                except NoSuchElementException:
                    print("Next button not found")
                    self.ui['status'].success("No more pages to scrape.")
                    break
                except Exception as e:
                    print(f"Pagination error: {e}")
                    break
                
            except Exception as e:
                print(f"Error on page {page}: {e}")
                traceback.print_exc()
                break

    # === NON-SELENIUM SCRAPERS (using requests) ===
    
    def scrape_nellis(self, url, start_page, end_page):
        print(f"\nStarting Nellis scraper (requests-based)")
        base_url = "https://www.nellisauction.com"
        current_url = url
        if not current_url.startswith("http"):
            current_url = f"https://{current_url}"
        
        links = []
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                print(f"\nFetching Nellis page {page}...")
                print(f"URL: {current_url}")
                
                self.ui['status'].info(f"Fetching Nellis page {page}...")
                req = requests.get(current_url, headers=self.headers)
                
                if req.status_code != 200:
                    print(f"Failed: HTTP {req.status_code}")
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {req.status_code}")
                    break
                
                soup = BeautifulSoup(req.text, "html.parser")
                products = soup.find_all("li", class_="__list-item-base")
                print(f"Found {len(products)} product links")
                
                if not products:
                    print("No products found")
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
                    print("No next page link found")
                    break
                
                current_url = base_url + next_page
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error while fetching page {page}: {e}")
                traceback.print_exc()
                break
        
        print(f"\nTotal product links collected: {len(links)}")
        total_products = len(links)
        processed = 0
        
        for link in links:
            if not self.running:
                break
            
            try:
                print(f"\nProcessing product {processed+1}/{total_products}")
                print(f"URL: {link}")
                
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
                print(f"Error processing product {processed+1}: {e}")
                traceback.print_exc()
                processed += 1

    def scrape_bidfta(self, url, start_page, end_page):
        print(f"\nStarting BidFTA scraper (requests-based)")
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
                print(f"\nFetching BidFTA page {page}...")
                page_url = f"{current_url}/{page}"
                print(f"URL: {page_url}")
                
                self.ui['status'].info(f"Fetching BidFTA page {page}...")
                req = requests.get(page_url, headers=self.headers)
                
                if req.status_code != 200:
                    print(f"Failed: HTTP {req.status_code}")
                    break
                
                soup = BeautifulSoup(req.text, "html.parser")
                div = soup.find("div", class_="grid grid-cols-1 gap-5 md:gap-6 pb-8 xl:pb-16 md:grid-cols-3 2xl:grid-cols-4")
                
                if not div:
                    print("No product grid found")
                    break
                
                products = div.find_all("div", class_="block")
                print(f"Found {len(products)} products")
                
                if not products:
                    print("No products in grid")
                    break
                
                new_links = 0
                for p in products:
                    link_tag = p.find("a")
                    if link_tag and link_tag.get("href"):
                        product_url = base_url + link_tag.get("href")
                        if product_url not in links:
                            links.append(product_url)
                            new_links += 1
                
                print(f"New links added: {new_links}")
                
                if new_links == 0:
                    print("No new links, ending")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error while fetching page {page}: {e}")
                traceback.print_exc()
                break
        
        print(f"\nTotal product links: {len(links)}")
        total_products = len(links)
        processed = 0
        
        for link in links:
            if not self.running:
                break
            
            try:
                print(f"\nProcessing product {processed+1}/{total_products}")
                print(f"URL: {link}")
                
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
                print(f"Error processing product {processed+1}: {e}")
                traceback.print_exc()
                processed += 1

    def scrape_astock(self, url, start_page, end_page):
        print(f"\nStarting A-Stock scraper (requests-based)")
        base_url = url.split("?")[0]
        page = start_page
        
        while self.running and (end_page == 0 or page <= end_page):
            try:
                print(f"\nFetching A-Stock page {page}...")
                current_url = f"{base_url}?page={page}"
                print(f"URL: {current_url}")
                
                self.ui['status'].info(f"Fetching A-Stock page {page}...")
                response = requests.get(current_url, headers=self.headers)
                
                if response.status_code != 200:
                    print(f"Failed: HTTP {response.status_code}")
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {response.status_code}")
                    break
                
                soup = BeautifulSoup(response.text, "html.parser")
                sections = soup.find_all("section")
                print(f"Found {len(sections)} sections")
                
                if len(sections) == 0:
                    print("No items found")
                    self.ui['status'].success("No items found. Scraping complete.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page)
                
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
                            total_items_on_page=len(sections)
                        )
                        
                    except Exception as e:
                        print(f"Error processing item {i}: {e}")
                        continue
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error fetching page {page}: {e}")
                traceback.print_exc()
                break



    def scrape_702auctions(self, url, start_page, end_page):
        print(f"\nStarting 702Auctions scraper (requests-based)")
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
                print(f"\nFetching 702Auctions page {page}...")
                current_url = f"{base_url}/?ViewStyle=list&StatusFilter=completed_only&SortFilterOptions=0&page={page}"
                print(f"URL: {current_url}")
                
                self.ui['status'].info(f"Fetching 702Auctions page {page}...")
                response = requests.get(current_url, headers=self.headers)
                
                if response.status_code != 200:
                    print(f"Failed: HTTP {response.status_code}")
                    self.ui['status'].error(f"Failed to fetch page {page}. Status code: {response.status_code}")
                    break
                
                soup = BeautifulSoup(response.text, "html.parser")
                sections = soup.find_all("section")
                print(f"Found {len(sections)} sections")
                
                if not sections:
                    print("No sections found")
                    self.ui['status'].success("No more items found on this page. Ending scrape.")
                    break
                
                self.ui['metrics']['pages'].metric("Pages Scraped", page + 1)
                
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
                            total_items_on_page=len(sections)
                        )
                        
                    except Exception as e:
                        continue
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error fetching page {page}: {e}")
                traceback.print_exc()
                break
