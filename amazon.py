import gc
import base64
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import re
import json
import random
import queue
import hashlib
import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

ZYTE_API_KEY = os.getenv('ZYTE_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL', "https://sjxkhpuaucenweapjlre.supabase.co")
SUPABASE_KEY = os.getenv('SUPABASE_KEY', "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNqeGtocHVhdWNlbndlYXBqbHJlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjMyNjIyMTYsImV4cCI6MjA3ODgzODIxNn0.2R7gf9pi0rdCq9CpK-IEmFOAvU69BrOULKYmID47FwQ")

if 'processed_data' in st.session_state:
    pass
st.cache_data.clear()

st.set_page_config(
    page_title="Amazon Product Viewer",
    page_icon="logo.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'fullscreen_mode' not in st.session_state:
    st.session_state.fullscreen_mode = False
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'failed_asins' not in st.session_state:
    st.session_state.failed_asins = []
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'processing_complete' not in st.session_state:
    st.session_state.processing_complete = False
if 'current_processing_id' not in st.session_state:
    st.session_state.current_processing_id = 0
if 'total_processing_count' not in st.session_state:
    st.session_state.total_processing_count = 0
if 'show_prices' not in st.session_state:
    st.session_state.show_prices = True

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def create_image_hash(image_url):
    return hashlib.md5(image_url.encode()).hexdigest()

def store_image_to_supabase(asin, image_url, source_type="amazon", retail_price=None):
    try:
        supabase = get_supabase_client()
        image_hash = create_image_hash(image_url)
        existing = supabase.table('product_images').select('*').eq('image_hash', image_hash).execute()
        
        if existing.data:
            return False
        
        data = {
            'asin': asin,
            'image_url': image_url,
            'image_hash': image_hash,
            'source_type': source_type,
            'retail_price': retail_price,
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        result = supabase.table('product_images').insert(data).execute()
        return bool(result.data)
            
    except Exception as e:
        return False

def delete_all_images_from_supabase():
    try:
        supabase = get_supabase_client()
        result = supabase.table('product_images').delete().neq('id', 0).execute()
        
        if hasattr(result, 'data'):
            return True
        else:
            return False
            
    except Exception as e:
        return False

def get_stored_images_count():
    try:
        supabase = get_supabase_client()
        result = supabase.table('product_images').select('id', count='exact').execute()
        return result.count if hasattr(result, 'count') else 0
    except:
        return 0

def load_stored_images_from_supabase(source_filter="amazon"):
    try:
        supabase = get_supabase_client()
        result = supabase.table('product_images').select('*').eq('source_type', source_filter).order('retail_price', desc=True, nullsfirst=False).execute()
        
        if result.data:
            stored_data = []
            for item in result.data:
                stored_data.append({
                    'Asin': item['asin'],
                    'Product_Image_URL': item['image_url'],
                    'Retail': item.get('retail_price', ''),
                    'Fetch_Success': True,
                    'Error': None,
                    'Source': item['source_type'],
                    'Stored_At': item['created_at']
                })
            
            df = pd.DataFrame(stored_data)
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        return pd.DataFrame()

def combine_stored_and_new_images(new_df=None, source_type="amazon"):
    stored_df = load_stored_images_from_supabase(source_type)
    
    if new_df is not None and not new_df.empty:
        if not stored_df.empty:
            for col in ['Asin', 'Product_Image_URL', 'Fetch_Success', 'Error']:
                if col not in stored_df.columns:
                    stored_df[col] = ''
                if col not in new_df.columns:
                    new_df[col] = ''
            
            combined_df = pd.concat([stored_df, new_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=['Product_Image_URL'], keep='first')
            return combined_df
        else:
            return new_df
    else:
        return stored_df

def generate_error_report(df, failed_asins, logs):
    report_data = []
    
    for asin in failed_asins:
        asin_row = df[df['Asin'] == asin].iloc[0] if 'Asin' in df.columns and not df[df['Asin'] == asin].empty else None
        asin_logs = [msg for level, msg in logs if str(asin) in str(msg)]
        
        error_category = "Unknown Error"
        error_detail = ""
        retry_recommended = "No"
        
        if any("404" in log or "not found" in log.lower() for log in asin_logs):
            error_category = "Product Not Found"
            error_detail = "ASIN does not exist on Amazon"
            retry_recommended = "No"
        elif any("robot" in log.lower() or "captcha" in log.lower() for log in asin_logs):
            error_category = "Bot Detection"
            error_detail = "CAPTCHA or bot check triggered"
            retry_recommended = "Yes"
        elif any("No image found" in log or "no image" in log.lower() for log in asin_logs):
            error_category = "No Image Available"
            error_detail = "Product page has no landingImage"
            retry_recommended = "Maybe"
        elif any("rate limit" in log.lower() or "429" in log for log in asin_logs):
            error_category = "Rate Limit"
            error_detail = "API rate limit exceeded"
            retry_recommended = "Yes"
        elif any("timeout" in log.lower() or "503" in log for log in asin_logs):
            error_category = "Timeout/Service Unavailable"
            error_detail = "Connection timeout or service unavailable"
            retry_recommended = "Yes"
        
        retail_price = ""
        if asin_row is not None:
            price_column_patterns = [
                'MSRP', 'msrp', 'EXT MSRP', 'ext msrp', 'Ext MSRP',
                'Retail', 'retail', 'RETAIL',
                'Price', 'price', 'PRICE',
                'Cost', 'cost', 'COST',
            ]
            for col in price_column_patterns:
                if col in df.columns and pd.notna(asin_row[col]):
                    retail_price = str(asin_row[col])
                    break
        
        report_data.append({
            'ASIN': asin,
            'Retail_Price': retail_price,
            'Error_Category': error_category,
            'Error_Detail': error_detail,
            'Retry_Recommended': retry_recommended,
            'Log_Summary': ' | '.join(asin_logs[:3]) if asin_logs else 'No logs found'
        })
    
    report_df = pd.DataFrame(report_data)
    summary_data = []
    total_failed = len(failed_asins)
    error_counts = report_df['Error_Category'].value_counts() if not report_df.empty else pd.Series()
    
    summary_data.append({
        'ASIN': '=== SUMMARY ===',
        'Retail_Price': '',
        'Error_Category': f'Total Failed: {total_failed}',
        'Error_Detail': '',
        'Retry_Recommended': '',
        'Log_Summary': ''
    })
    
    for error_type, count in error_counts.items():
        percentage = (count / total_failed * 100) if total_failed > 0 else 0
        summary_data.append({
            'ASIN': '',
            'Retail_Price': '',
            'Error_Category': error_type,
            'Error_Detail': f'{count} failures ({percentage:.1f}%)',
            'Retry_Recommended': '',
            'Log_Summary': ''
        })
    
    summary_data.append({
        'ASIN': '',
        'Retail_Price': '',
        'Error_Category': '',
        'Error_Detail': '',
        'Retry_Recommended': '',
        'Log_Summary': ''
    })
    
    summary_data.append({
        'ASIN': '=== DETAILED ERRORS ===',
        'Retail_Price': '',
        'Error_Category': '',
        'Error_Detail': '',
        'Retry_Recommended': '',
        'Log_Summary': ''
    })
    
    summary_df = pd.DataFrame(summary_data)
    final_report = pd.concat([summary_df, report_df], ignore_index=True)
    
    return final_report

def add_custom_css():
    st.markdown("""
    <style>
    :root {
        --primary-color: #232F3E;
        --accent-color: #FF9900;
        --text-color: #232F3E;
        --light-bg: #f5f5f5;
        --card-bg: white;
        --header-font: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        --body-font: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }

    div[data-testid="stExpander"] {
        background-color: #1e1e1e !important;
        border: 1px solid #333333 !important;
        border-radius: 8px !important;
    }
    
    div[data-testid="stExpander"]:hover {
        background-color: #2a2a2a !important;
        border-color: #4a4a4a !important;
    }
    
    div[data-testid="stExpander"] summary {
        background-color: #1e1e1e !important;
        color: white !important;
        padding: 12px 16px !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    
    div[data-testid="stExpander"] summary:hover {
        background-color: #2a2a2a !important;
        color: white !important;
    }
    
    div[data-testid="stExpander"] > div[role="region"] {
        background-color: #1e1e1e !important;
        border-top: 1px solid #333333 !important;
        padding: 0 !important;
    }
    
    div[data-testid="stProgress"] > div {
        background-color: #e0e0e0 !important;
        border-radius: 10px !important;
        height: 8px !important;
    }
    
    div[data-testid="stProgress"] > div > div {
        background-color: #FF9900 !important;
        border-radius: 10px !important;
    }
    
    .stMarkdown p {
        color: #232F3E !important;
    }

    .password-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 20px;
        background-color: var(--card-bg);
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin: 20px auto;
        max-width: 400px;
    }
    
    .top-logo-container {
        text-align: center;
        padding: 10px 0 5px 0;
        background-color: white;
    }

    .top-center-logo {
        width:  350px;
        height: 150px;
        object-fit: contain;
    }

    .login-logo {
        width: 100px;
        height: 100px;
        margin-bottom: 20px;
        object-fit: contain;
    }

    .main-header {
        background-color: var(--primary-color);
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        color: white;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        text-align: center;
    }

    .main-header h1 {
        font-family: var(--header-font);
        font-weight: 700;
        margin: 0;
        font-size: 2.5rem;
        color: white;
        white-space: nowrap;
    }

    .subtitle {
        font-size: 1.1rem;
        opacity: 0.9;
        margin-top: 5px;
        white-space: nowrap;
    }

    .password-container h2 {
        color: #FF9900;
        font-family: var(--header-font);
        margin-bottom: 15px;
        font-size: 1.5rem;
    }

    .accent-text {
        color: var(--accent-color);
    }
    
    .upload-container {
        background-color: var(--light-bg);
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        border: 2px dashed #ccc;
        margin-bottom: 15px;
        color: var(--text-color);
    }
    
    .upload-container h3 {
        color: var(--text-color);
        margin-bottom: 10px;
    }
    
    .upload-container p {
        color: var(--text-color);
        margin: 5px 0;
    }
    
    .upload-icon {
        font-size: 2.5rem;
        color: var(--accent-color);
        margin-bottom: 10px;
    }
    
    .filters-panel {
        background-color: var(--light-bg);
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        color: var(--text-color);
    }
    
    .filters-panel h3 {
        color: var(--text-color);
        margin: 0 0 10px 0;
    }
    
    .filters-panel p {
        color: var(--text-color);
        margin: 5px 0;
    }
    
    .price-overlay {
        position: absolute;
        top: 5px;
        right: 5px;
        background-color: rgba(0,0,0,0.8);
        color: white;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 11px;
        font-weight: bold;
    }
    
    .price-overlay-fullscreen {
        position: absolute;
        top: 5px;
        right: 5px;
        background-color: rgba(0,0,0,0.8);
        color: white;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 9px;
        font-weight: bold;
    }
    
    .footer {
        text-align: center;
        padding: 15px;
        margin-top: 20px;
        border-top: 1px solid #eee;
        color: #777;
        font-size: 0.85rem;
    }
    
    .raw-data-container {
        background-color: #f8f9fa;
        border-radius: 5px;
        padding: 10px;
        margin: 10px 0;
        overflow-x: auto;
        font-family: monospace;
        font-size: 0.9em;
        white-space: pre-wrap;
        word-break: break-word;
    }
    
    .failed-asin-list {
        background-color: #ff5555;
        border-left: 5px solid #ff0000;
        padding: 15px;
        margin: 15px 0;
        border-radius: 5px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
    
    .failed-asin-title {
        color: black;
        font-weight: bold;
        font-size: 16px;
        margin-bottom: 10px;
        text-shadow: 1px 1px 2px rgba(255,255,255,0.5);
    }
    
    .failed-asin-item {
        margin: 5px 0;
        padding: 5px 10px;
        background-color: white;
        border-radius: 3px;
        color: #d9534f;
        font-family: monospace;
        font-weight: bold;
        font-size: 14px;
        display: inline-block;
        margin-right: 5px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }

    @media (max-width: 768px) {
        .image-grid {
            grid-template-columns: repeat(3, 1fr);
        }
    }
    </style>
    """, unsafe_allow_html=True)

def get_logo_base64():
    try:
        with open("logo.png", "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        return ""

def verify_password():
    st.markdown("""
    <div class="top-logo-container">
        <img src="data:image/png;base64,{logo_base64}" class="top-center-logo" alt="Logo">
    </div>
    """.format(logo_base64=get_logo_base64()), unsafe_allow_html=True)
    
    st.markdown("""
    <div class="password-container">
        <h2>Enter Password</h2>
    </div>
    """, unsafe_allow_html=True)
    
    with st.form(key="password_form"):
        password = st.text_input("Password", type="password", key="password_input")
        submit_button = st.form_submit_button("Login", help="Click to verify password")
        
        if submit_button:
            if password == "nick123":
                st.session_state.authenticated = True
                st.success("Login successful!")
                st.rerun()
            else:
                st.markdown('<p class="error-message">Incorrect password. Please try again.</p>', unsafe_allow_html=True)

def add_log(message, level="info"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    log_entry = (level, f"[{timestamp}] {message}")
    st.session_state.logs.append(log_entry)
    # Keep only last 50 logs to save memory
    if len(st.session_state.logs) > 50:
        st.session_state.logs = st.session_state.logs[-50:]

def get_amazon_product_details(asin, log_queue, processing_id, total_count, retail_price=None):
    """OPTIMIZED: Single attempt, no delays - Zyte handles everything"""
    st.session_state.current_processing_id = processing_id
    st.session_state.total_processing_count = total_count
    
    product_details = {
        'asin': asin,
        'image_url': '',
        'success': False,
        'retry_count': 0,
        'error': None
    }

    # SINGLE ATTEMPT - NO RETRIES, NO DELAYS
    # Zyte API handles retries, rate limiting, and proxy rotation internally
    url = f"https://www.amazon.com/dp/{asin}"
    
    try:
        if not ZYTE_API_KEY:
            product_details['error'] = 'Zyte API key not configured'
            return product_details
        
        api_response = requests.post(
            "https://api.zyte.com/v1/extract",
            auth=(ZYTE_API_KEY, ""),
            json={
                "url": url,
                "httpResponseBody": True,
                "followRedirect": True,
            },
            timeout=60
        )
        
        if api_response.status_code == 200:
            response_data = api_response.json()
            http_response_body = base64.b64decode(response_data["httpResponseBody"])
            resp_text = http_response_body.decode('utf-8', errors='ignore')
            soup = BeautifulSoup(resp_text, 'html.parser')
            img_tag = soup.find("img", {"id": "landingImage"})
            
            if img_tag and img_tag.get("data-a-dynamic-image"):
                try:
                    images_dict = json.loads(img_tag["data-a-dynamic-image"])
                    largest_image = max(images_dict.keys(), 
                                      key=lambda x: images_dict[x][0] * images_dict[x][1])
                    
                    if '._' in largest_image:
                        base_url = largest_image.split('._')[0]
                        largest_image = base_url + "._AC_SL1500_.jpg"
                    
                    product_details['image_url'] = largest_image
                    product_details['success'] = True
                    store_image_to_supabase(asin, largest_image, "amazon", retail_price)
                    return product_details
                except Exception as e:
                    product_details['error'] = f'Image parse error: {str(e)}'

            if img_tag and img_tag.get("src"):
                src_url = img_tag["src"]
                if '._' in src_url:
                    base_url = src_url.split('._')[0]
                    src_url = base_url + "._AC_SL1500_.jpg"
                product_details['image_url'] = src_url
                product_details['success'] = True
                store_image_to_supabase(asin, src_url, "amazon", retail_price)
                return product_details
        
        elif api_response.status_code == 422:
            error_detail = api_response.json().get('detail', 'Unknown error')
            product_details['error'] = f'Validation error: {error_detail}'
        elif api_response.status_code == 429:
            product_details['error'] = 'Rate limit exceeded'
        elif api_response.status_code == 503:
            product_details['error'] = 'Service unavailable (503)'
        elif api_response.status_code == 404:
            product_details['error'] = 'Product not found (404)'
        else:
            product_details['error'] = f'HTTP {api_response.status_code}'
    
    except Exception as e:
        product_details['error'] = str(e)[:100]
    
    if not product_details['success']:
        if not product_details['error']:
            product_details['error'] = 'No image found'
    
    return product_details

def detect_csv_type(df):
    df_clean = df.dropna(how='all').copy()
    
    if df_clean.empty:
        return 'unknown'
    
    columns_lower = [col.lower().strip() for col in df_clean.columns]
    
    if ('listing id' in columns_lower and 'url' in columns_lower) or \
       ('listing_id' in columns_lower and 'url' in columns_lower) or \
       ('listingid' in columns_lower and 'url' in columns_lower):
        return 'excel_format'
    
    amazon_columns = ['asin', 'sku', 'product_id'] 
    if any(amazon_col in columns_lower for amazon_col in amazon_columns):
        return 'amazon'
    
    for index, row in df_clean.head(20).iterrows():
        for value in row:
            if pd.notna(value) and value != 'nan':
                value_str = str(value).strip().lower()
                if ('http' in value_str and 
                    ('.jpg' in value_str or '.png' in value_str or '.jpeg' in value_str or 
                     '.gif' in value_str or '.webp' in value_str)):
                    return 'direct_urls'
    
    return 'unknown'

def process_amazon_data(df, max_rows=None):
    """OPTIMIZED: Fast processing with live speed tracking"""
    if max_rows is not None and max_rows > 0 and max_rows < len(df):
        df = df.head(max_rows)
    
    asin_col = None
    for col in df.columns:
        if col.lower().strip() in ['asin', 'sku']:
            asin_col = col
            break

    if not asin_col:
        st.error(f"No ASIN/SKU column found. Available columns: {list(df.columns)}")
        return None

    price_column_patterns = [
        'MSRP', 'msrp', 'EXT MSRP', 'ext msrp', 'Ext MSRP',
        'Retail', 'retail', 'RETAIL',
        'Price', 'price', 'PRICE',
        'Cost', 'cost', 'COST',
        'List Price', 'list price', 'LIST PRICE',
        'Unit Price', 'unit price', 'UNIT PRICE',
    ]
    
    retail_col = None
    for pattern in price_column_patterns:
        if pattern in df.columns:
            retail_col = pattern
            break
    
    if not retail_col:
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['msrp', 'retail', 'price', 'cost']):
                retail_col = col
                break
    
    if retail_col:
        st.info(f"💰 Found price column: '{retail_col}' - prices will be preserved for sorting!")

    df_copy = df.copy()
    df_copy = df_copy.rename(columns={asin_col: 'Asin'})
    
    st.session_state.logs = []
    st.session_state.failed_asins = []
    st.session_state.processing_complete = False
    st.session_state.current_processing_id = 0
    st.session_state.total_processing_count = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    current_status = st.empty()
    
    unique_asins = df_copy['Asin'].unique()
    total_asins = len(unique_asins)
    
    # Track start time for speed calculation
    start_time = time.time()
    
    status_text.text(f"🚀 FAST MODE: Processing {total_asins} ASINs - NO delays!")
    add_log(f"Starting OPTIMIZED processing of {total_asins} unique ASINs from column '{asin_col}'")
    
    log_queue = queue.Queue()
    
    def process_log_queue(log_queue):
        while not log_queue.empty():
            try:
                item = log_queue.get()
                if isinstance(item, tuple) and len(item) == 2:
                    level, message = item
                    st.session_state.logs.append((level, message))
                else:
                    st.session_state.logs.append(("error", f"Malformed log entry: {str(item)}"))
            except Exception as e:
                st.session_state.logs.append(("error", f"Error processing log entry: {str(e)}"))
    
    def process_batch(asins, start_index):
        product_details_dict = {}
        batch_log_queue = queue.Queue()
        
        for i, asin in enumerate(asins):
            processing_id = start_index + i + 1
            
            retail_price = None
            if retail_col:
                asin_row = df_copy[df_copy['Asin'] == asin]
                if not asin_row.empty:
                    price_value = asin_row.iloc[0][retail_col]
                    if pd.notna(price_value):
                        retail_price = str(price_value).replace('$', '').replace(',', '').replace('#', '')
                        try:
                            retail_price = float(retail_price)
                        except:
                            retail_price = str(price_value)
            
            current_status.text(f"🔄 Processing: {asin} ({processing_id}/{total_asins})...")
            
            product_details = get_amazon_product_details(asin, batch_log_queue, processing_id, total_asins, retail_price)
            product_details_dict[asin] = product_details
            
            if product_details['success'] and product_details['image_url']:
                current_status.text(f"✅ {asin} - Image found!")
            elif product_details.get('error'):
                error_msg = product_details['error'][:50]
                current_status.text(f"❌ {asin} - Error: {error_msg}")
            else:
                current_status.text(f"⚠️ {asin} - No image found")
            
            if not product_details['success'] or not product_details['image_url']:
                st.session_state.failed_asins.append(asin)
        
        while not batch_log_queue.empty():
            log_queue.put(batch_log_queue.get())
        
        process_log_queue(batch_log_queue)
        
        return product_details_dict
    
    batch_size = 1
    all_product_details = {}
    
    for i in range(0, len(unique_asins), batch_size):
        batch_asins = unique_asins[i:i+batch_size]
        
        progress = i / len(unique_asins)
        progress_bar.progress(progress)
        
        # Calculate speed and ETA
        elapsed = time.time() - start_time
        if elapsed > 0:
            rate = (i + 1) / elapsed  # ASINs per second
            rate_per_min = rate * 60  # ASINs per minute
            remaining = len(unique_asins) - (i + 1)
            eta_seconds = remaining / rate if rate > 0 else 0
            eta_minutes = eta_seconds / 60
            
            status_text.text(
                f"Progress: {i+1}/{len(unique_asins)} | "
                f"✅ {len(all_product_details) - len(st.session_state.failed_asins)} | "
                f"❌ {len(st.session_state.failed_asins)} | "
                f"Speed: {rate_per_min:.1f}/min | "
                f"ETA: {eta_minutes:.1f} mins"
            )
        
        batch_results = process_batch(batch_asins, i)
        all_product_details.update(batch_results)
        
        while not log_queue.empty():
            level, message = log_queue.get()
            st.session_state.logs.append((level, message))
        
        progress = (i + len(batch_asins)) / len(unique_asins)
        progress_bar.progress(progress)
        
        # Aggressive garbage collection every 50 ASINs
        if (i + 1) % 50 == 0:
            gc.collect()
    
    enriched_data = []
    
    for _, row in df_copy.iterrows():
        asin = row['Asin']
        product_info = all_product_details.get(asin, {
            'asin': asin,
            'image_url': '',
            'success': False,
            'error': 'Processing skipped'
        })
        
        new_row = row.to_dict()
        new_row.update({
            'Product_Image_URL': product_info['image_url'],
            'Fetch_Success': product_info['success'],
            'Error': product_info.get('error', None)
        })
        
        enriched_data.append(new_row)
    
    enriched_df = pd.DataFrame(enriched_data)
    
    st.session_state.processing_complete = True
    
    progress_bar.progress(1.0)
    status_text.empty()
    current_status.empty()
    
    # Calculate total time
    total_time = time.time() - start_time
    
    success_count = len(enriched_df[enriched_df['Fetch_Success'] == True])
    failed_count = len(st.session_state.failed_asins)
    
    st.markdown("---")
    st.success(f"✅ Processing complete in {total_time/60:.1f} minutes! Average speed: {total_asins/(total_time/60):.1f} ASINs/min")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("✅ Successful", success_count, help="ASINs with images retrieved successfully")
    
    with col2:
        st.metric("❌ Failed", failed_count, help="ASINs that failed to retrieve images")
    
    with col3:
        success_rate = (success_count / total_asins * 100) if total_asins > 0 else 0
        st.metric("📊 Success Rate", f"{success_rate:.1f}%", help="Percentage of successful retrievals")
    
    if st.session_state.failed_asins:
        for failed_asin in st.session_state.failed_asins[:20]:
            st.markdown(f'<span class="failed-asin-item">{failed_asin}</span>', unsafe_allow_html=True)
        
        if failed_count > 20:
            st.markdown(f'<span class="failed-asin-item">... and {failed_count - 20} more</span>', unsafe_allow_html=True)
        
        st.markdown('</div></div>', unsafe_allow_html=True)
        
        st.markdown("---")
        
        error_report = generate_error_report(
            enriched_df, 
            st.session_state.failed_asins, 
            st.session_state.logs
        )
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            with st.expander("📋 Error Summary Preview", expanded=True):
                error_counts = error_report['Error_Category'].value_counts()
                error_counts = error_counts[error_counts.index != '']
                
                if not error_counts.empty:
                    for error_type, count in error_counts.items():
                        if error_type not in ['=== SUMMARY ===', '=== DETAILED ERRORS ===']:
                            percentage = (count / failed_count * 100) if failed_count > 0 else 0
                            st.markdown(f"**{error_type}:** {count} ({percentage:.1f}%)")
        
        with col2:
            st.download_button(
                label="📥 Download Error Report",
                data=error_report.to_csv(index=False),
                file_name=f"error_report_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                key="error_report_download",
                help="Download detailed report of all failed ASINs",
                type="primary"
            )
    
    # Final garbage collection
    gc.collect()
    
    return enriched_df

def process_direct_urls_data(df, max_rows=None):
    if max_rows is not None and max_rows > 0 and max_rows < len(df):
        df = df.head(max_rows)
    
    st.session_state.logs = []
    st.session_state.failed_asins = []
    st.session_state.processing_complete = False
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_rows = len(df)
    status_text.text(f"Processing {total_rows} image URLs...")
    add_log(f"Starting processing of {total_rows} direct image URLs")
    
    enriched_data = []
    
    for index, row in df.iterrows():
        progress = (index + 1) / total_rows
        progress_bar.progress(progress)
        status_text.text(f"Processing {index + 1} of {total_rows} images ({int(progress*100)}%)")
        
        row_dict = row.to_dict()
        
        image_url = None
        listing_id = None
        
        for key, value in row_dict.items():
            if pd.notna(value) and 'http' in str(value) and ('.jpg' in str(value) or '.png' in str(value) or '.jpeg' in str(value)):
                image_url = str(value).strip()
                break
        
        for key, value in row_dict.items():
            if pd.notna(value) and str(value).isdigit():
                listing_id = str(value).strip()
                break
        
        if not listing_id:
            listing_id = f"Item_{index + 1}"
        
        new_row = row_dict.copy()
        new_row.update({
            'Listing_ID': listing_id,
            'Product_Image_URL': image_url if image_url else '',
            'Fetch_Success': True if image_url else False,
            'Error': None if image_url else 'No image URL found'
        })
        
        if not image_url:
            st.session_state.failed_asins.append(listing_id)
            add_log(f"No image URL found for Listing ID: {listing_id}", "warning")
        else:
            add_log(f"Found image URL for Listing ID: {listing_id}", "success")
        
        enriched_data.append(new_row)
    
    enriched_df = pd.DataFrame(enriched_data)
    
    st.session_state.processing_complete = True
    progress_bar.progress(1.0)
    status_text.empty()
    
    if st.session_state.failed_asins:
        failed_count = len(st.session_state.failed_asins)
        st.markdown(f"""
        <div class="failed-asin-list">
            <div class="failed-asin-title" style="color: black !important;">⚠️ No image URLs found for {failed_count} items:</div>
            <div>
        """, unsafe_allow_html=True)
        
        for failed_item in st.session_state.failed_asins:
            st.markdown(f'<span class="failed-asin-item">{failed_item}</span>', unsafe_allow_html=True)
        
        st.markdown('</div></div>', unsafe_allow_html=True)
    
    add_log(f"Processing complete! Processed {len(enriched_data)} items", "success")
    return enriched_df

def process_excel_format_data(df, max_rows=None):
    if max_rows is not None and max_rows > 0 and max_rows < len(df):
        df = df.head(max_rows)
    
    st.session_state.logs = []
    st.session_state.failed_asins = []
    st.session_state.processing_complete = False
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    listing_id_col = None
    url_col = None
    
    for col in df.columns:
        col_lower = col.lower().strip()
        if 'listing' in col_lower and 'id' in col_lower:
            listing_id_col = col
        elif col_lower == 'url':
            url_col = col
    
    if not listing_id_col or not url_col:
        st.error("Could not find 'Listing ID' and 'url' columns in the Excel file.")
        return None
    
    df_clean = df.dropna(how='all').copy()
    total_rows = len(df_clean)
    
    status_text.text(f"Processing {total_rows} Excel rows...")
    add_log(f"Starting processing of {total_rows} Excel rows with Listing ID and URL columns")
    add_log(f"Using columns: '{listing_id_col}' and '{url_col}'")
    
    enriched_data = []
    
    for index, row in df_clean.iterrows():
        progress = (index + 1) / total_rows
        progress_bar.progress(progress)
        status_text.text(f"Processing {index + 1} of {total_rows} images ({int(progress*100)}%)")
        
        listing_id = row[listing_id_col] if pd.notna(row[listing_id_col]) else f"Item_{index + 1}"
        image_url = row[url_col] if pd.notna(row[url_col]) else ''
        
        listing_id = str(listing_id).strip()
        image_url = str(image_url).strip()
        
        valid_url = False
        if image_url and image_url != 'nan' and 'http' in image_url.lower():
            if any(ext in image_url.lower() for ext in ['.jpg', '.png', '.jpeg', '.gif', '.webp']):
                valid_url = True
        
        new_row = row.to_dict()
        new_row.update({
            'Listing_ID': listing_id,
            'Product_Image_URL': image_url if valid_url else '',
            'Fetch_Success': valid_url,
            'Error': None if valid_url else 'Invalid or missing image URL'
        })
        
        if not valid_url:
            st.session_state.failed_asins.append(listing_id)
            add_log(f"Invalid image URL for Listing ID: {listing_id}", "warning")
        else:
            add_log(f"Valid image URL found for Listing ID: {listing_id}", "success")
        
        enriched_data.append(new_row)
        
    enriched_df = pd.DataFrame(enriched_data)
    
    st.session_state.processing_complete = True
    progress_bar.progress(1.0)
    status_text.empty()
    
    if st.session_state.failed_asins:
        failed_count = len(st.session_state.failed_asins)
        st.markdown(f"""
        <div class="failed-asin-list">
            <div class="failed-asin-title" style="color: black !important;">⚠️ Invalid image URLs found for {failed_count} items:</div>
            <div>
        """, unsafe_allow_html=True)
        
        for failed_item in st.session_state.failed_asins[:10]:
            st.markdown(f'<span class="failed-asin-item">{failed_item}</span>', unsafe_allow_html=True)
        
        if failed_count > 10:
            st.markdown(f'<span class="failed-asin-item">... and {failed_count - 10} more</span>', unsafe_allow_html=True)
        
        st.markdown('</div></div>', unsafe_allow_html=True)
    
    add_log(f"Processing complete! Processed {len(enriched_data)} items", "success")
    
    return enriched_df

def process_csv_data(df, max_rows=None):
    csv_type = detect_csv_type(df)
    
    if csv_type == 'amazon':
        if not any(col.lower() in ['asin', 'sku'] for col in df.columns):
            st.error("The CSV file must contain an 'Asin' column for Amazon products.")
            return None
        return process_amazon_data(df, max_rows)
    elif csv_type == 'excel_format':
        return process_excel_format_data(df, max_rows)
    elif csv_type == 'direct_urls':
        return process_direct_urls_data(df, max_rows)
    else:
        st.error("Could not detect CSV format. Please ensure your file contains either 'Asin' column for Amazon products, 'Listing ID' and 'url' columns for Excel format, or direct image URLs.")
        return None

def display_product_grid(df, search_term=None, min_price=None, max_price=None, sort_by=None):
    if df is None or df.empty:
        st.warning("No data available to display.")
        return
        
    filtered_df = df.copy()
    
    price_column_patterns = [
        'MSRP', 'msrp', 'EXT MSRP', 'ext msrp', 'Ext MSRP',
        'Retail', 'retail', 'RETAIL',
        'Price', 'price', 'PRICE',
        'Cost', 'cost', 'COST',
        'List Price', 'list price', 'LIST PRICE',
        'Unit Price', 'unit price', 'UNIT PRICE',
    ]
    
    retail_col = None
    
    for pattern in price_column_patterns:
        if pattern in filtered_df.columns:
            retail_col = pattern
            break
    
    if not retail_col:
        for col in filtered_df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['msrp', 'retail', 'price', 'cost']):
                retail_col = col
                break
    
    if retail_col:
        try:
            filtered_df[f'{retail_col}_numeric'] = filtered_df[retail_col].astype(str).str.replace('$', '').str.replace(',', '').str.replace('#', '')
            filtered_df[f'{retail_col}_numeric'] = pd.to_numeric(filtered_df[f'{retail_col}_numeric'], errors='coerce')
            
            filtered_df = filtered_df.sort_values(by=f'{retail_col}_numeric', ascending=False, na_position='last')
            
            st.info(f"📊 Images automatically sorted by {retail_col} (highest to lowest)")
        except Exception as e:
            st.warning(f"Could not sort by {retail_col}: {str(e)}")
    
    asin_column = None
    if 'Asin' in filtered_df.columns:
        asin_column = 'Asin'
    else:
        for col in filtered_df.columns:
            if col.lower().strip() in ['asin', 'sku']:
                asin_column = col
                break
    
    if search_term and asin_column:
        search_term_lower = search_term.lower()
        filtered_df = filtered_df[filtered_df[asin_column].str.lower().str.contains(search_term_lower, na=False)]
    
    if filtered_df.empty:
        st.warning("No products match your search criteria.")
        return
    
    import streamlit.components.v1 as components
    
    html_content = """
    <style>
        .image-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            grid-auto-rows: 1fr;
            gap: 4px;
            width: 100%;
        }
        
        .grid-item {
            aspect-ratio: 1;
            overflow: hidden;
            position: relative;
        }
        
        .grid-item img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            background-color: white;
        }
        
        .price-overlay {
            position: absolute;
            top: 5px;
            right: 5px;
            background-color: rgba(0,0,0,0.8);
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
        }
        
        .scrollable-container {
            height: 100%;
            overflow-y: auto;
        }
    </style>
    
    <div class="scrollable-container">
        <div class="image-grid">
    """
    
    for i, product in filtered_df.iterrows():
        image_url = product['Product_Image_URL']
        
        if not image_url:
            image_url = "https://placehold.co/200x200?text=No+Image"
        
        price_display = ""
        if retail_col and pd.notna(product[retail_col]) and st.session_state.show_prices:
            price_value = str(product[retail_col])
            if not price_value.startswith('$'):
                price_display = f"${price_value}"
            else:
                price_display = price_value
            
        html_content += f"""
        <div class="grid-item">
            <img src="{image_url}" alt="Product">
            {f'<div class="price-overlay">{price_display}</div>' if price_display else ''}
        </div>
        """
    
    html_content += """
        </div>
    </div>
    """
    
    components.html(html_content, height=800, scrolling=True)

def display_fullscreen_grid(df, search_term=None, min_price=None, max_price=None, sort_by=None):
    if df is None or df.empty:
        st.warning("No data available to display.")
        return
        
    filtered_df = df.copy()
    
    price_column_patterns = [
        'MSRP', 'msrp', 'EXT MSRP', 'ext msrp', 'Ext MSRP',
        'Retail', 'retail', 'RETAIL',
        'Price', 'price', 'PRICE',
        'Cost', 'cost', 'COST',
        'List Price', 'list price', 'LIST PRICE',
        'Unit Price', 'unit price', 'UNIT PRICE',
    ]
    
    retail_col = None
    
    for pattern in price_column_patterns:
        if pattern in filtered_df.columns:
            retail_col = pattern
            break
    
    if not retail_col:
        for col in filtered_df.columns:
            col_lower = col.lower().strip()
            if any(keyword in col_lower for keyword in ['msrp', 'retail', 'price', 'cost']):
                retail_col = col
                break
    
    if retail_col:
        try:
            filtered_df[f'{retail_col}_numeric'] = filtered_df[retail_col].astype(str).str.replace('$', '').str.replace(',', '').str.replace('#', '')
            filtered_df[f'{retail_col}_numeric'] = pd.to_numeric(filtered_df[f'{retail_col}_numeric'], errors='coerce')
            
            filtered_df = filtered_df.sort_values(by=f'{retail_col}_numeric', ascending=False, na_position='last')
        except Exception as e:
            pass
    
    asin_column = None
    if 'Asin' in filtered_df.columns:
        asin_column = 'Asin'
    else:
        for col in filtered_df.columns:
            if col.lower().strip() in ['asin', 'sku']:
                asin_column = col
                break
    
    if search_term and asin_column:
        search_term_lower = search_term.lower()
        filtered_df = filtered_df[filtered_df[asin_column].str.lower().str.contains(search_term_lower, na=False)]
    
    if filtered_df.empty:
        st.warning("No products match your search criteria.")
        return
    
    import streamlit.components.v1 as components
    
    exit_container = st.container()
    with exit_container:
        if st.button("✕", key="exit_fullscreen_amazon", help="Exit fullscreen"):
            st.session_state.fullscreen_mode = False
            st.rerun()
    
    html_content = """
    <style>
        body {
            margin: 0;
            padding: 0;
            overflow: hidden;
        }
        
        .fullscreen-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: white; 
            z-index: 9999;
            overflow: auto;
            padding: 10px;
            box-sizing: border-box;
        }
        
        .fullscreen-exit-button {
            position: fixed;
            top: 15px;
            right: 15px;
            background-color: rgba(0,0,0,0.7);
            color: white;
            border: none;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            font-size: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 10000;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            transition: background-color 0.2s, transform 0.2s;
        }
        
        .fullscreen-exit-button:hover {
            background-color: rgba(255,0,0,0.8);
            transform: scale(1.1);
        }
        
        .fullscreen-gallery-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 8px;
            width: 100%;
            padding-top: 10px;
        }
        
        .gallery-item {
            aspect-ratio: 1;
            background-color: white;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s;
            position: relative;
        }
        
        .gallery-item:hover {
            transform: scale(1.05);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            z-index: 1;
        }
        
        .gallery-item img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            background-color: white;
        }
        
        .gallery-item .asin-tooltip {
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            background-color: rgba(0,0,0,0.7);
            color: white;
            padding: 4px;
            font-size: 10px;
            opacity: 0;
            transition: opacity 0.2s;
            text-align: center;
        }
        
        .gallery-item:hover .asin-tooltip {
            opacity: 1;
        }
        
        .price-overlay-fullscreen {
            position: absolute;
            top: 5px;
            right: 5px;
            background-color: rgba(0,0,0,0.8);
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 9px;
            font-weight: bold;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .gallery-item {
            animation: fadeIn 0.3s ease forwards;
            animation-delay: calc(var(--item-index) * 0.02s);
            opacity: 0;
        }
    </style>
    
    <div class="fullscreen-container">
        <div class="fullscreen-gallery-grid">
    """
    
    for i, product in filtered_df.iterrows():
        image_url = product['Product_Image_URL']
        
        if asin_column and asin_column in product:
            asin = product[asin_column]
        else:
            asin = f"Item_{i}"
        
        if not image_url:
            image_url = "https://placehold.co/200x200?text=No+Image"
        
        price_display = ""
        if retail_col and pd.notna(product[retail_col]) and st.session_state.show_prices:
            price_value = str(product[retail_col])
            if not price_value.startswith('$'):
                price_display = f"${price_value}"
            else:
                price_display = price_value
            
        html_content += f"""
        <div class="gallery-item" style="--item-index: {i}">
            <img src="{image_url}" alt="Product {asin}">
            {f'<div class="price-overlay-fullscreen">{price_display}</div>' if price_display else ''}
            <div class="asin-tooltip">{asin}{f' - {price_display}' if price_display else ''}</div>
        </div>
        """
    
    html_content += """
        </div>
    </div>
    
    <script>
        document.addEventListener('keydown', function(event) {
            if (event.key === "Escape") {
                window.parent.location.reload();
            }
        });
        document.addEventListener('DOMContentLoaded', function() {
            const streamlitElements = document.querySelectorAll('.stApp > div:not(.element-container), header, footer, .stToolbar');
            streamlitElements.forEach(el => {
                el.style.display = 'none';
            });
            
            const container = document.querySelector('.fullscreen-container');
            if (container) {
                container.style.position = 'fixed';
                container.style.top = '0';
                container.style.left = '0';
                container.style.width = '100vw';
                container.style.height = '100vh';
                container.style.zIndex = '999999';
            }
        });
    </script>
    """
    
    components.html(html_content, height=1000, scrolling=True)

def render_amazon_grid_tab():
    stored_data = load_stored_images_from_supabase("amazon")
    
    if stored_data.empty:
        st.warning("No Amazon data has been processed yet. Please upload and process a CSV file with ASINs in the Upload tab.")
        return
    
    st.session_state.processed_data = stored_data
    
    csv_type = detect_csv_type(st.session_state.processed_data)
    if csv_type not in ['amazon', 'unknown']:
        st.warning("This tab is for Amazon products only. Please use the Excel Grid Images tab for other formats.")
        return
    
    st.markdown("""
    <div class="filters-panel">
        <h3>Amazon Grid Images</h3>
        <p>Amazon product images sorted by retail price (highest to lowest)</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        search_term = st.text_input("Search by ASIN", key="amazon_grid_search")
    
    with col2:
        stored_count = get_stored_images_count()
        st.metric("Stored Amazon Images", stored_count)
    
    with col3:
        if 'show_delete_confirm' not in st.session_state:
            st.session_state.show_delete_confirm = False
            
        if not st.session_state.show_delete_confirm:
            if st.button("🗑️ Delete All", key="delete_all_btn", help="Delete all Amazon images from Supabase", type="secondary"):
                st.session_state.show_delete_confirm = True
                st.rerun()
        else:
            col3a, col3b = st.columns(2)
            with col3a:
                if st.button("✅ Confirm", key="confirm_delete", type="primary"):
                    if delete_all_images_from_supabase():
                        st.session_state.processed_data = pd.DataFrame()
                        st.success("All Amazon images deleted!")
                    st.session_state.show_delete_confirm = False
                    st.rerun()
            with col3b:
                if st.button("❌ Cancel", key="cancel_delete", type="secondary"):
                    st.session_state.show_delete_confirm = False
                    st.rerun()
    
    col4, col5, col6 = st.columns([2, 1, 1])
    
    with col4:
        if st.button("🔄 Reload Amazon Images", key="reload_btn", help="Reload Amazon images from Supabase"):
            st.session_state.processed_data = load_stored_images_from_supabase("amazon")
            st.rerun()
    
    with col5:
        fullscreen_button = st.button("🖼️ Full Screen View", key="amazon_grid_fullscreen_btn", help="View images in a fullscreen 7-column grid")
    
    with col6:
        if st.button(
            f"{'🏷️ Show Prices' if not st.session_state.show_prices else '🚫 Hide Prices'}", 
            key="toggle_prices_btn",
            help="Toggle price visibility on images"
        ):
            st.session_state.show_prices = not st.session_state.show_prices
            st.rerun()
    
    total_products = len(st.session_state.processed_data)
    st.write(f"Displaying {total_products} Amazon images in 5-column grid")
    
    if fullscreen_button:
        st.session_state.fullscreen_mode = True
        st.rerun()

    if st.session_state.fullscreen_mode:
        display_fullscreen_grid(
            st.session_state.processed_data,
            search_term=search_term if search_term else None
        )
        
    else:
        display_product_grid(
            st.session_state.processed_data,
            search_term=search_term
        )
    
    try:
        if st.download_button(
            label="Export Amazon Data to CSV",
            data=st.session_state.processed_data.to_csv(index=False),
            file_name="amazon_images_data.csv",
            mime="text/csv",
            key="amazon_grid_export_unique"
        ):
            st.success("Amazon data exported successfully!")
    except Exception as e:
        st.error(f"Error exporting data: {str(e)}")

def render_excel_grid_tab():
    if st.session_state.processed_data is None:
        st.warning("No data has been processed yet. Please upload and process a CSV file in the Upload tab.")
        return
    
    csv_type = detect_csv_type(st.session_state.processed_data)
    if csv_type not in ['direct_urls', 'excel_format']:
        st.warning("This tab is for Excel files with direct image URLs. Please use the Amazon Grid Images tab for Amazon products.")
        return
    
    st.markdown("""
    <div class="filters-panel">
        <h3>Excel Grid Images</h3>
        <p>Simple grid view of images from Excel file</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        total_products = len(st.session_state.processed_data)
        st.write(f"Displaying {total_products} images from Excel file in 5-column grid")
    
    with col2:
        fullscreen_button = st.button("🖼️ Full Screen View", key="excel_grid_fullscreen_btn", help="View images in a fullscreen 7-column grid")
    
    if fullscreen_button:
        st.session_state.fullscreen_mode = True
        st.rerun()
    
    if st.session_state.fullscreen_mode:
        display_simple_fullscreen_grid(st.session_state.processed_data)
    else:
        display_simple_product_grid(st.session_state.processed_data)
    
    try:
        if st.download_button(
            label="Export Excel Data to CSV",
            data=st.session_state.processed_data.to_csv(index=False),
            file_name="excel_images_grid.csv",
            mime="text/csv",
            key="excel_grid_export_unique"
        ):
            st.success("Excel data exported successfully!")
    except Exception as e:
        st.error(f"Error exporting data: {str(e)}")

def display_simple_product_grid(df):
    if df is None or df.empty:
        st.warning("No data available to display.")
        return

    import streamlit.components.v1 as components

    html_content = """
    <style>
        .masonry-container {
            height: 800px;
            overflow-y: auto;
            padding: 5px;
            background-color: #f0f0f0;
            border-radius: 5px;
        }
        .masonry-grid {
            column-count: 5;
            column-gap: 5px;
        }
        .masonry-item {
            margin-bottom: 5px;
            break-inside: avoid;
            border-radius: 4px;
            overflow: hidden;
            background-color: white;
        }
        .masonry-item img {
            display: block;
            width: 100%;
            height: auto;
            object-fit: cover;
        }
    </style>
    
    <div class="masonry-container">
        <div class="masonry-grid">
    """
    
    for i, product in df.iterrows():
        image_url = product.get('Product_Image_URL', '') 
        
        if image_url and image_url.strip() != '':
            html_content += f"""
            <div class="masonry-item">
                <img src="{image_url}" alt="Product Image">
            </div>
            """
        else:
            html_content += f"""
            <div class="masonry-item" style="height:150px; display:flex; align-items:center; justify-content:center; text-align:center; color: #888; font-size: 12px;">
                No Image Found
            </div>
            """

    html_content += """
        </div> 
    </div>
    """
    
    components.html(html_content, height=810)

def display_simple_fullscreen_grid(df):
    if df is None or df.empty:
        st.warning("No data available to display.")
        return

    import streamlit.components.v1 as components

    exit_container = st.container()
    with exit_container:
        if st.button("✕", key="exit_fullscreen_excel_grid", help="Exit fullscreen (or press Esc)"):
            st.session_state.fullscreen_mode = False
            st.rerun()

    html_content = """
    <style>
        body {
            margin: 0;
            padding: 0;
            overflow: hidden;
        }
        
        .fullscreen-wrapper {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: #1e1e1e;
            overflow-y: auto;
            padding: 10px;
            box-sizing: border-box;
            z-index: 9990;
        }
        
        .masonry-grid-fullscreen {
            column-count: 7;
            column-gap: 8px;
        }
        
        .masonry-item-fullscreen {
            background-color: white;
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 8px;
            break-inside: avoid;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            animation: fadeIn 0.4s ease forwards;
            animation-delay: calc(var(--item-index) * 0.02s);
            opacity: 0;
        }
        
        .masonry-item-fullscreen img {
            display: block;
            width: 100%;
            height: auto;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(15px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
    
    <div class="fullscreen-wrapper">
        <div class="masonry-grid-fullscreen">
    """
    
    for i, product in df.iterrows():
        image_url = product.get('Product_Image_URL', '')
        
        if image_url and image_url.strip() != '':
            style_attr = f'style="--item-index: {i};"' 
            html_content += f"""
            <div class="masonry-item-fullscreen" {style_attr}>
                <img src="{image_url}" alt="Product Image">
            </div>
            """
    
    html_content += """
        </div>
    </div>
    
    <script>
        function enterFullscreenMode() {
            const streamlitDoc = window.parent.document;
            if (!streamlitDoc) return;

            const iframe = streamlitDoc.querySelector('iframe[srcdoc*="fullscreen-wrapper"]');
            
            const mainAppContainer = streamlitDoc.querySelector('.stApp');
            if (mainAppContainer) {
                Array.from(mainAppContainer.children).forEach(child => {
                    if (iframe && child.contains(iframe)) {
                    } else {
                        child.style.display = 'none';
                    }
                });
            }
        }
        
        function handleEscKey(event) {
            if (event.key === "Escape") {
                const exitButton = window.parent.document.querySelector('button[key="exit_fullscreen_excel_grid"]');
                if (exitButton) {
                    exitButton.click();
                }
            }
        }

        window.addEventListener('load', enterFullscreenMode);
        window.parent.document.addEventListener('keydown', handleEscKey);

        window.addEventListener('beforeunload', () => {
             window.parent.document.removeEventListener('keydown', handleEscKey);
        });
    </script>
    """
    
    components.html(html_content, height=1000)

def render_upload_tab():
    st.markdown("""
    <div class="upload-container">
        <div class="upload-icon">📂</div>
        <h3>Upload your CSV file</h3>
        <p><strong>Supported formats:</strong></p>
        <p>• Amazon ASINs: CSV with 'Asin' column</p>
        <p>• Excel Format: CSV/Excel with 'Listing ID' and 'url' columns</p>
        <p>• Direct Image URLs: CSV with direct links to .jpg/.png images</p>
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("", type=["csv", "xlsx", "xls"], key="main_csv_uploader")
    
    process_limit = st.number_input(
        "Limit number of rows to process (leave at 0 to process all):",
        min_value=0,
        value=0,
        step=1,
        help="Set a limit on how many rows to process. This can be useful for testing or to reduce processing time.",
        key="process_limit_input"
    )
    
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                excel_file = pd.ExcelFile(uploaded_file)
                sheet_names = excel_file.sheet_names
                if not sheet_names:
                    st.error("No sheets found in the Excel file.")
                    return
                
                last_sheet = sheet_names[-1]
                df = pd.read_excel(uploaded_file, sheet_name=last_sheet)
                
                df.columns = [f'Column_{i}' if col.startswith('Unnamed:') else col for i, col in enumerate(df.columns)]
                
                df = df.dropna(how='all')
                df = df.reset_index(drop=True)
            
            csv_type = detect_csv_type(df)
            total_rows = len(df)
            
            if csv_type == 'amazon':
                asin_col = None
                for col in df.columns:
                    if col.lower().strip() in ['asin', 'sku']:
                        asin_col = col
                        break
                
                if asin_col:
                    unique_asins = df[asin_col].nunique()
                    st.info(f"📦 **Amazon CSV detected** - File contains {total_rows} rows with {unique_asins} unique ASINs in column '{asin_col}'.")
                else:
                    st.info(f"📦 **Amazon CSV detected** - File contains {total_rows} rows.")
                    
            elif csv_type == 'excel_format':
                st.info(f"📋 **Excel Format detected** - File contains {total_rows} rows with 'Listing ID' and 'url' columns.")
                
            elif csv_type == 'direct_urls':
                st.info(f"🖼️ **Direct Image URLs detected** - File contains {total_rows} rows with image URLs found.")
                        
            else:
                st.warning(f"⚠️ **Unknown format** - Could not detect CSV type.")
                st.write("**Debug Info:**")
                st.write(f"- Columns: {list(df.columns)}")
                st.write(f"- First row sample: {df.iloc[0].to_dict()}")
            
            if process_limit > 0 and process_limit < total_rows:
                st.warning(f"You've chosen to process only {process_limit} rows out of {total_rows} total rows.")
            
            if st.button("🚀 Process (FAST MODE - No Delays!)", key="process_button_unique", type="primary", help="Optimized for speed - Zyte handles rate limiting"):
                if csv_type == 'unknown':
                    st.error("Could not detect file format. Please ensure your file contains either 'Asin' column for Amazon products or direct image URLs.")
                else:
                    with st.spinner("⚡ Processing at maximum speed..."):
                        max_rows = process_limit if process_limit > 0 else None
                        new_data = process_csv_data(df, max_rows)
                        
                        if new_data is not None:
                            if csv_type == 'amazon':
                                st.session_state.processed_data = combine_stored_and_new_images(new_data, "amazon")
                                st.success("✅ Amazon data processed successfully! Check Amazon Grid Images tab to view all Amazon images (stored + new).")
                            else:
                                st.session_state.processed_data = new_data
                                st.success("✅ Data processed successfully! Check Excel Grid Images tab to view images (temporary, not stored).")
                        else:
                            st.error("❌ Failed to process data. Please check your file format.")
        
        except Exception as e:
            st.error(f"Error reading the file: {str(e)}")
            st.markdown("""
            <div class="raw-data-container">
            <p>Troubleshooting tips:</p>
            <ul>
                <li>Ensure your file is properly formatted (CSV or Excel)</li>
                <li>For Amazon: Check that your file contains an 'ASIN' column</li>
                <li>For Direct URLs: Ensure your file contains direct links to images (.jpg, .png, .jpeg)</li>
                <li>Verify there are no special characters or encoding issues</li>
            </ul>
            </div>
            """, unsafe_allow_html=True)

def main():
    add_custom_css()
    
    if not ZYTE_API_KEY:
        st.error("⚠️ Zyte API key not found!")
        st.markdown("""
        ### Setup Instructions:
        1. Create a `.env` file in your project directory
        2. Add your Zyte API key to the `.env` file:
           ```
           ZYTE_API_KEY=your_actual_api_key_here
           ```
        3. Restart the app
        """)
        st.info("Get your Zyte API key from: https://www.zyte.com/")
        return
    
    if not st.session_state.authenticated:
        verify_password()
        return
    
    st.markdown("""
    <div class="top-logo-container">
        <img src="data:image/png;base64,{logo_base64}" class="top-center-logo" alt="Logo">
    </div>
    """.format(logo_base64=get_logo_base64()), unsafe_allow_html=True)
    st.markdown("""
    <div class="main-header">
        <h1>Universal <span class="accent-text">Image Viewer</span></h1>
        <div class="subtitle">⚡ OPTIMIZED - No Delays - Zyte Handles Everything - Process 1000+ ASINs Fast!</div>
    </div>
    """, unsafe_allow_html=True)
    
    query_params = st.query_params
    if 'fullscreen' in query_params and query_params.get('fullscreen') == 'true':
        if st.session_state.processed_data is not None:
            search_term = query_params.get('search', '')
            
            display_fullscreen_grid(
                st.session_state.processed_data,
                search_term=search_term if search_term else None
            )
            return
    
    tab_names = ["📤 Upload CSV", "📦 Amazon Grid Images", "📋 Excel Grid Images"]
    tabs = st.tabs(tab_names)
    
    with tabs[0]:
        render_upload_tab()
    
    with tabs[1]:
        render_amazon_grid_tab()
    
    with tabs[2]:
        render_excel_grid_tab()
    
    st.markdown("""
    <div class="footer">
        <p>Universal Image Viewer App | Optimized for 1000+ ASINs | Support for Amazon ASINs & Direct Image URLs</p>
        <p>⚡ Fast Mode: No unnecessary delays - Zyte API handles rate limiting & retries</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
