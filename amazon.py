import base64
import streamlit as st
import pandas as pd
from curl_cffi import requests
from bs4 import BeautifulSoup
import time
import re
import json
import random
import queue
import hashlib
from supabase import create_client, Client

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

# Supabase configuration
SUPABASE_URL = "https://sjxkhpuaucenweapjlre.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNqeGtocHVhdWNlbndlYXBqbHJlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjMyNjIyMTYsImV4cCI6MjA3ODgzODIxNn0.2R7gf9pi0rdCq9CpK-IEmFOAvU69BrOULKYmID47FwQ"

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def create_image_hash(image_url):
    return hashlib.md5(image_url.encode()).hexdigest()

def store_image_to_supabase(asin, image_url, source_type="amazon"):
    try:
        supabase = get_supabase_client()
        
        image_hash = create_image_hash(image_url)
        
        # Check if image already exists
        existing = supabase.table('product_images').select('*').eq('image_hash', image_hash).execute()
        
        if existing.data:
            add_log(f"Image already exists for ASIN {asin}, skipping", "warning")
            return False
        
        # Insert new image
        data = {
            'asin': asin,
            'image_url': image_url,
            'image_hash': image_hash,
            'source_type': source_type,
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        result = supabase.table('product_images').insert(data).execute()
        
        if result.data:
            add_log(f"Stored image for ASIN {asin} to Supabase", "success")
            return True
        else:
            add_log(f"Failed to store image for ASIN {asin}", "error")
            return False
            
    except Exception as e:
        add_log(f"Supabase error for ASIN {asin}: {str(e)}", "error")
        return False

def delete_all_images_from_supabase():
    try:
        supabase = get_supabase_client()
        result = supabase.table('product_images').delete().neq('id', 0).execute()
        
        if hasattr(result, 'data'):
            add_log("All images deleted from Supabase", "success")
            return True
        else:
            add_log("Failed to delete images from Supabase", "error")
            return False
            
    except Exception as e:
        add_log(f"Error deleting images: {str(e)}", "error")
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
        result = supabase.table('product_images').select('*').eq('source_type', source_filter).order('created_at', desc=True).execute()
        
        if result.data:
            stored_data = []
            for item in result.data:
                stored_data.append({
                    'Asin': item['asin'],
                    'Product_Image_URL': item['image_url'],
                    'Fetch_Success': True,
                    'Error': None,
                    'Source': item['source_type'],
                    'Stored_At': item['created_at']
                })
            
            df = pd.DataFrame(stored_data)
            add_log(f"Loaded {len(stored_data)} stored {source_filter} images from Supabase", "success")
            return df
        else:
            add_log(f"No stored {source_filter} images found in Supabase", "info")
            return pd.DataFrame()
            
    except Exception as e:
        add_log(f"Error loading stored {source_filter} images: {str(e)}", "error")
        return pd.DataFrame()

def combine_stored_and_new_images(new_df=None, source_type="amazon"):
    stored_df = load_stored_images_from_supabase(source_type)
    
    if new_df is not None and not new_df.empty:
        # Combine stored and new images
        if not stored_df.empty:
            # Make sure columns match
            for col in ['Asin', 'Product_Image_URL', 'Fetch_Success', 'Error']:
                if col not in stored_df.columns:
                    stored_df[col] = ''
                if col not in new_df.columns:
                    new_df[col] = ''
            
            # Combine dataframes
            combined_df = pd.concat([stored_df, new_df], ignore_index=True)
            # Remove duplicates based on image URL
            combined_df = combined_df.drop_duplicates(subset=['Product_Image_URL'], keep='first')
            add_log(f"Combined {len(stored_df)} stored + {len(new_df)} new = {len(combined_df)} total {source_type} images", "info")
            return combined_df
        else:
            return new_df
    else:
        # Only return stored images
        return stored_df

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
                

    /* FIX: Expander styling - prevent white background on hover */
    div[data-testid="stExpander"] {
        background-color: #1e1e1e !important;
        border: 1px solid #333333 !important;
        border-radius: 8px !important;
    }
    
    div[data-testid="stExpander"]:hover {
        background-color: #2a2a2a !important;
        border-color: #4a4a4a !important;
    }
    
    /* FIX: Expander header */
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
    
    /* FIX: Expander content area */
    div[data-testid="stExpander"] > div[role="region"] {
        background-color: #1e1e1e !important;
        border-top: 1px solid #333333 !important;
        padding: 0 !important;
    }
    
    /* FIX: Progress bar styling */
    div[data-testid="stProgress"] > div {
        background-color: #e0e0e0 !important;
        border-radius: 10px !important;
        height: 8px !important;
    }
    
    div[data-testid="stProgress"] > div > div {
        background-color: #FF9900 !important;
        border-radius: 10px !important;
    }
    
    /* FIX: Status text visibility */
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

    .password-input {
        padding: 8px;
        font-size: 14px;
        width: 100%;
        border: 2px solid #ccc;
        border-radius: 5px;
        margin-bottom: 10px;
    }

    .password-button {
        background-color: var(--accent-color);
        color: white;
        font-weight: 600;
        padding: 8px 16px;
        border-radius: 5px;
        border: none;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .password-button:hover {
        background-color: #e68a00;
        transform: translateY(-2px);
    }

    .error-message {
        color: #d9534f;
        font-size: 12px;
        margin-top: 8px;
        text-align: center;
    }

    .fullscreen-gallery-container {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: #1e1e1e;
        z-index: 9999;
        overflow: hidden;
    }

    .fullscreen-gallery-grid {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 8px;
        padding: 10px;
        overflow-y: auto;
        height: 100vh;
        box-sizing: border-box;
    }

    .fullscreen-gallery-item {
        aspect-ratio: 1;
        background-color: white;
        border-radius: 4px;
        overflow: hidden;
        position: relative;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        transition: transform 0.2s ease;
    }

    .fullscreen-gallery-item:hover {
        transform: scale(1.05);
        z-index: 100;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    }

    .fullscreen-gallery-item img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        background-color: white;
    }

    .fullscreen-controls {
        position: fixed;
        top: 15px;
        right: 15px;
        display: flex;
        gap: 10px;
        z-index: 10000;
    }

    .fullscreen-exit-button {
        background-color: rgba(0,0,0,0.7);
        color: white;
        border: none;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        font-size: 18px;
        transition: all 0.2s ease;
    }

    .fullscreen-exit-button:hover {
        background-color: rgba(255,0,0,0.8);
        transform: scale(1.1);
    }

    .image-tooltip {
        position: absolute;
        bottom: 0;
        left: 0;
        width: 100%;
        background-color: rgba(0,0,0,0.7);
        color: white;
        padding: 4px 8px;
        font-size: 12px;
        opacity: 0;
        transition: opacity 0.3s;
        text-align: center;
        border-radius: 0 0 4px 4px;
    }

    .fullscreen-gallery-item:hover .image-tooltip {
        opacity: 1;
    }

    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .fullscreen-gallery-item {
        animation: fadeIn 0.3s ease forwards;
        animation-delay: calc(var(--item-index) * 0.02s);
        opacity: 0;
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
    
    .custom-button {
        background-color: var(--accent-color);
        color: white;
        font-weight: 600;
        padding: 10px 20px;
        border-radius: 5px;
        border: none;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .custom-button:hover {
        background-color: #e68a00;
        transform: translateY(-2px);
    }
    
    .loading-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 30px 0;
    }
    
    .loading-spinner {
        border: 5px solid #f3f3f3;
        border-top: 5px solid var(--accent-color);
        border-radius: 50%;
        width: 40px;
        height: 40px;
        animation: spin 1s linear infinite;
        margin-bottom: 15px;
    }
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    .stats-container {
        display: flex;
        justify-content: space-between;
        margin-bottom: 15px;
    }
    
    .stat-card {
        background-color: white;
        border-radius: 10px;
        padding: 12px;
        flex: 1;
        margin: 0 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        text-align: center;
    }
    
    .stat-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--primary-color);
        margin-bottom: 4px;
    }
    
    .stat-label {
        font-size: 0.85rem;
        color: #777;
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

    .log-container {
        background-color: #1e1e1e;
        color: #dcdcdc;
        font-family: 'Courier New', monospace;
        padding: 12px;
        border-radius: 5px;
        margin: 10px 0;
        max-height: 300px;
        overflow-y: auto;
    }
    
    .log-entry {
        margin: 4px 0;
        white-space: pre-wrap;
        line-height: 1.4;
    }
    
    .log-info {
        color: #6a9955;
    }
    
    .log-warning {
        color: #dcdcaa;
    }
    
    .log-error {
        color: #f14c4c;
    }
    
    .log-success {
        color: #4ec9b0;
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
        color: white;
        font-weight: bold;
        font-size: 16px;
        margin-bottom: 10px;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.5);
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
    
    .processing-indicator {
        position: fixed;
        bottom: 20px;
        right: 20px;
        background-color: rgba(0,0,0,0.8);
        color: white;
        padding: 10px 15px;
        border-radius: 5px;
        z-index: 1000;
        font-size: 0.9rem;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
    }
    
    .processing-id {
        font-weight: bold;
        color: #4ec9b0;
    }
    
    .processing-total {
        font-weight: bold;
        color: #dcdcaa;
    }
    
    .image-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 2px;
        align-items: stretch;
    }

    .grid-item {
        flex: 1 0 150px;
        height: 150px;
        overflow: hidden;
        margin: 1px;
    }

    .grid-item img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    
    .scrollable-container {
        height: 800px;
        overflow-y: auto;
        padding: 5px;
        background-color: #f0f0f0;
        border-radius: 5px;
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

def display_logs(log_container):
    log_display = '<div class="log-container">\n'
    
    for entry in st.session_state.logs:
        try:
            if isinstance(entry, tuple) and len(entry) == 2:
                level, message = entry
                log_display += f'<div class="log-{level}">{message}</div>\n'
            else:
                log_display += f'<div class="log-error">Invalid log entry: {str(entry)}</div>\n'
        except Exception as e:
            log_display += f'<div class="log-error">Error displaying log entry: {str(e)}</div>\n'
    
    log_display += '</div>'
    log_container.markdown(log_display, unsafe_allow_html=True)

def get_amazon_product_details(asin, log_queue, processing_id, total_count):
    st.session_state.current_processing_id = processing_id
    st.session_state.total_processing_count = total_count
    
    log_queue.put(('info', f'Starting to process ASIN: {asin} ({processing_id}/{total_count})'))
    
    product_details = {
        'asin': asin,
        'image_url': '',
        'success': False,
        'retry_count': 0,
        'error': None
    }

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "Referer": "https://www.google.com/"
    }
    
    cookies = {
        "session-id": str(random.randint(100000000, 999999999)),
        "session-id-time": str(int(time.time())),
        "i18n-prefs": "USD"
    }

    for attempt in range(3):
        url = f"https://www.amazon.com/dp/{asin}"
        
        log_queue.put(('info', f'ASIN {asin}: Attempt {attempt+1}/3 started'))
        
        if attempt > 0:
            sleep_time = 2 + random.uniform(1, 3)
            log_queue.put(('info', f'ASIN {asin}: Waiting {sleep_time:.2f} seconds before retry'))
            time.sleep(sleep_time)
        
        try:
            resp = requests.get(
                url,
                headers=headers,
                cookies=cookies,
                impersonate="chrome",
                timeout=15
            )
            
            if resp.status_code == 200:
                log_queue.put(('success', f'ASIN {asin}: Retrieved page on attempt {attempt+1}'))
                
                soup = BeautifulSoup(resp.text, 'html.parser')
                
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
                        log_queue.put(('success', f'ASIN {asin}: Found image on attempt {attempt+1}'))
                        
                        # Store to Supabase
                        store_image_to_supabase(asin, largest_image, "amazon")
                        
                        return product_details
                    except Exception:
                        pass

                if img_tag and img_tag.get("src"):
                    src_url = img_tag["src"]
                    if '._' in src_url:
                        base_url = src_url.split('._')[0]
                        src_url = base_url + "._AC_SL1500_.jpg"
                    product_details['image_url'] = src_url
                    product_details['success'] = True
                    log_queue.put(('success', f'ASIN {asin}: Found image on attempt {attempt+1}'))
                    
                    # Store to Supabase
                    store_image_to_supabase(asin, src_url, "amazon")
                    
                    return product_details
                
                log_queue.put(('warning', f'ASIN {asin}: No image found on attempt {attempt+1}. Will retry.'))
            
            else:
                log_queue.put(('error', f'ASIN {asin}: Bad status code {resp.status_code} on attempt {attempt+1}'))
        
        except Exception as e:
            log_queue.put(('error', f'ASIN {asin}: Error on attempt {attempt+1}: {str(e)}'))
    
    if not product_details['success']:
        log_queue.put(('error', f'ASIN {asin}: Failed after 3 attempts'))
        product_details['error'] = 'Failed to retrieve product data after 3 attempts'
    
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

def process_direct_urls_data(df, max_rows=None):
    if max_rows is not None and max_rows > 0 and max_rows < len(df):
        df = df.head(max_rows)
    
    st.session_state.logs = []
    st.session_state.failed_asins = []
    st.session_state.processing_complete = False
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    log_expander = st.expander("Processing Log (Live)", expanded=True)
    log_container = log_expander.empty()
    
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
        
        log_display = '<div class="log-container">\n'
        for level, message in st.session_state.logs:
            log_display += f'<div class="log-{level}">{message}</div>\n'
        log_display += '</div>'
        log_container.markdown(log_display, unsafe_allow_html=True)
        
        time.sleep(0.05)
    
    enriched_df = pd.DataFrame(enriched_data)
    
    st.session_state.processing_complete = True
    progress_bar.progress(1.0)
    status_text.empty()
    
    if st.session_state.failed_asins:
        failed_count = len(st.session_state.failed_asins)
        st.markdown(f"""
        <div class="failed-asin-list">
            <div class="failed-asin-title">⚠️ No image URLs found for {failed_count} items:</div>
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
    log_expander = st.expander("Processing Log (Live)", expanded=True)
    log_container = log_expander.empty()
    
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
        
        log_display = '<div class="log-container">\n'
        for level, message in st.session_state.logs:
            log_display += f'<div class="log-{level}">{message}</div>\n'
        log_display += '</div>'
        log_container.markdown(log_display, unsafe_allow_html=True)
        
        time.sleep(0.1)
        
    enriched_df = pd.DataFrame(enriched_data)
    
    st.session_state.processing_complete = True
    progress_bar.progress(1.0)
    status_text.empty()
    
    if st.session_state.failed_asins:
        failed_count = len(st.session_state.failed_asins)
        st.markdown(f"""
        <div class="failed-asin-list">
            <div class="failed-asin-title">⚠️ Invalid image URLs found for {failed_count} items:</div>
            <div>
        """, unsafe_allow_html=True)
        
        for failed_item in st.session_state.failed_asins[:10]:
            st.markdown(f'<span class="failed-asin-item">{failed_item}</span>', unsafe_allow_html=True)
        
        if failed_count > 10:
            st.markdown(f'<span class="failed-asin-item">... and {failed_count - 10} more</span>', unsafe_allow_html=True)
        
        st.markdown('</div></div>', unsafe_allow_html=True)
    
    add_log(f"Processing complete! Processed {len(enriched_data)} items", "success")
    log_display = '<div class="log-container">\n'
    for level, message in st.session_state.logs:
        log_display += f'<div class="log-{level}">{message}</div>\n'
    log_display += '</div>'
    log_container.markdown(log_display, unsafe_allow_html=True)
    
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

def process_amazon_data(df, max_rows=None):
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

    df_copy = df.copy()
    df_copy = df_copy.rename(columns={asin_col: 'Asin'})
    
    st.session_state.logs = []
    st.session_state.failed_asins = []
    st.session_state.processing_complete = False
    st.session_state.current_processing_id = 0
    st.session_state.total_processing_count = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    processing_status = st.empty()
    log_expander = st.expander("Processing Log (Live)", expanded=True)
    log_container = log_expander.empty()
    
    log_container.markdown('<div class="log-container">', unsafe_allow_html=True)
    
    unique_asins = df_copy['Asin'].unique()
    total_asins = len(unique_asins)
    
    status_text.text(f"Processing {total_asins} unique Amazon products...")
    add_log(f"Starting processing of {total_asins} unique ASINs from column '{asin_col}'")
    
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
            product_details = get_amazon_product_details(asin, batch_log_queue, processing_id, total_asins)
            product_details_dict[asin] = product_details
            
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
        status_text.text(f"Processing batch {i//batch_size + 1} of {(len(unique_asins) + batch_size - 1) // batch_size}")
        
        processing_status.markdown(f"""
        <div class="processing-indicator">
            Processing ID: <span class="processing-id">{i+1}</span> / <span class="processing-total">{len(unique_asins)}</span>
        </div>
        """, unsafe_allow_html=True)
        
        batch_results = process_batch(batch_asins, i)
        all_product_details.update(batch_results)
        
        while not log_queue.empty():
            level, message = log_queue.get()
            st.session_state.logs.append((level, message))
        
        log_display = '<div class="log-container">\n'
        for level, message in st.session_state.logs:
            log_display += f'<div class="log-{level}">{message}</div>\n'
        log_display += '</div>'
        log_container.markdown(log_display, unsafe_allow_html=True)
        
        progress = (i + len(batch_asins)) / len(unique_asins)
        progress_bar.progress(progress)
        status_text.text(f"Processed {i + len(batch_asins)} of {len(unique_asins)} products ({int(progress*100)}%)")
        
        time.sleep(0.1)
    
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
    processing_status.empty()
    
    if st.session_state.failed_asins:
        failed_count = len(st.session_state.failed_asins)
        st.markdown(f"""
        <div class="failed-asin-list">
            <div class="failed-asin-title">⚠️ Failed to retrieve images for {failed_count} ASINs:</div>
            <div>
        """, unsafe_allow_html=True)
        
        for failed_asin in st.session_state.failed_asins:
            st.markdown(f'<span class="failed-asin-item">{failed_asin}</span>', unsafe_allow_html=True)
        
        st.markdown('</div></div>', unsafe_allow_html=True)
    
    return enriched_df

def display_fullscreen_grid(df, search_term=None, min_price=None, max_price=None, sort_by=None):
    if df is None or df.empty:
        st.warning("No data available to display.")
        return
        
    filtered_df = df.copy()
    
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
            
        html_content += f"""
        <div class="gallery-item" style="--item-index: {i}">
            <img src="{image_url}" alt="Product {asin}">
            <div class="asin-tooltip">{asin}</div>
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

def display_product_grid(df, search_term=None, min_price=None, max_price=None, sort_by=None):
    if df is None or df.empty:
        st.warning("No data available to display.")
        return
        
    filtered_df = df.copy()
    
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
        }
        
        .grid-item img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            background-color: white;
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
            
        html_content += f"""
        <div class="grid-item">
            <img src="{image_url}" alt="Product">
        </div>
        """
    
    html_content += """
        </div>
    </div>
    """
    
    components.html(html_content, height=800, scrolling=True)

def render_amazon_grid_tab():
    # ALWAYS reload from Supabase when visiting this tab
    stored_data = load_stored_images_from_supabase("amazon")
    
    if stored_data.empty:
        st.warning("No Amazon data has been processed yet. Please upload and process a CSV file with ASINs in the Upload tab.")
        return
    
    # Update session state with stored data
    st.session_state.processed_data = stored_data
    
    csv_type = detect_csv_type(st.session_state.processed_data)
    if csv_type not in ['amazon', 'unknown']:
        st.warning("This tab is for Amazon products only. Please use the Excel Grid Images tab for other formats.")
        return
    
    st.markdown("""
    <div class="filters-panel">
        <h3>Amazon Grid Images</h3>
        <p>Amazon product images in a grid layout (includes stored Amazon images only)</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Supabase Status Panel
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
    
    col4, col5 = st.columns([2, 1])
    
    with col4:
        if st.button("🔄 Reload Amazon Images", key="reload_btn", help="Reload Amazon images from Supabase"):
            st.session_state.processed_data = load_stored_images_from_supabase("amazon")
            st.rerun()
    
    with col5:
        fullscreen_button = st.button("🖼️ Full Screen View", key="amazon_grid_fullscreen_btn", help="View images in a fullscreen 7-column grid")
    
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

    html_content = f"""
    <style>
        .masonry-container {{
            height: 800px;
            overflow-y: auto;
            padding: 5px;
            background-color: #f0f0f0;
            border-radius: 5px;
        }}
        .masonry-grid {{
            column-count: 5;
            column-gap: 5px;
        }}
        .masonry-item {{
            margin-bottom: 5px;
            break-inside: avoid;
            border-radius: 4px;
            overflow: hidden;
            background-color: white;
        }}
        .masonry-item img {{
            display: block;
            width: 100%;
            height: auto;
            object-fit: cover;
        }}
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
            
            if st.button("Process and Fetch Product Images", key="process_button_unique", help="Click to start processing the uploaded file"):
                if csv_type == 'unknown':
                    st.error("Could not detect file format. Please ensure your file contains either 'Asin' column for Amazon products or direct image URLs.")
                else:
                    with st.spinner("Processing data and fetching images..."):
                        max_rows = process_limit if process_limit > 0 else None
                        new_data = process_csv_data(df, max_rows)
                        
                        if new_data is not None:
                            if csv_type == 'amazon':
                                # Combine with stored Amazon images only
                                st.session_state.processed_data = combine_stored_and_new_images(new_data, "amazon")
                                st.success("Amazon data processed successfully! Check Amazon Grid Images tab to view all Amazon images (stored + new).")
                            else:
                                # Don't store Excel/Direct URL images, just use new data
                                st.session_state.processed_data = new_data
                                st.success("Data processed successfully! Check Excel Grid Images tab to view images (temporary, not stored).")
                        else:
                            st.error("Failed to process data. Please check your file format.")
        
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
        <div class="subtitle">Upload CSV files with Amazon ASINs or direct image URLs to view images in grid format</div>
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
        <p>Universal Image Viewer App | Support for Amazon ASINs & Direct Image URLs</p>
        <p>Enhanced for reliable image retrieval and grid display from multiple sources</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
