import streamlit as st
import pandas as pd
import io
from datetime import datetime
from cryptography.fernet import Fernet
import base64
import json
import statistics
import time
import sys
import importlib.util

# Force clear cache and rerun
st.cache_data.clear()
st.cache_resource.clear()

# --- Dependency Handling ---
# Attempt to import the user's custom scraper class. If it fails, define a placeholder.
try:
    from scraper import AuctionScraper
except ImportError:
    st.warning("`scraper.py` not found. Using a placeholder class for demonstration.")
    class AuctionScraper:
        """A placeholder class to allow the application to run without the actual scraper.py file."""
        def __init__(self, gemini_api_keys=None, ui_placeholders=None):
            self._is_running = False
            self.ui_placeholders = ui_placeholders
            st.toast("Mock Scraper Initialized.")

        def run(self, site_name, url, start, end):
            self._is_running = True
            st.toast(f"Mock scraping started for {site_name}...")
            if self.ui_placeholders:
                self.ui_placeholders['status'].info("Scraping in progress...")
                for i in range(101):
                    if not self._is_running:
                        self.ui_placeholders['status'].warning("Scraping stopped by user.")
                        return []
                    self.ui_placeholders['metrics']['pages'].metric("Pages Scraped", f"{i // 10}/10")
                    self.ui_placeholders['metrics']['lots'].metric("Lots Scraped", i * 2)
                    self.ui_placeholders['progress'].progress(i)
                    time.sleep(0.02)
            return [
                {'Title': 'Sample Item 1 (from Mock Scraper)', 'Current Bid': '$50', 'Retail Price': '$200', 'Recovery': '25.00%'},
                {'Title': 'Sample Item 2 (from Mock Scraper)', 'Current Bid': '$120', 'Retail Price': '$150', 'Recovery': '80.00%'}
            ]

        def stop(self):
            self._is_running = False
            st.toast("Mock scraping stop signal sent.")

# Attempt to import functions from amazon.py. If it fails, define placeholders.
try:
    spec = importlib.util.spec_from_file_location("amazon_module", "amazon.py")
    amazon_module = importlib.util.module_from_spec(spec)
    sys.modules["amazon_module"] = amazon_module
    spec.loader.exec_module(amazon_module)
    from amazon_module import get_logo_base64, render_upload_tab, render_amazon_grid_tab, render_excel_grid_tab
    AMAZON_AVAILABLE = True
except Exception as e:
    st.error(f"Error loading amazon.py: {type(e).__name__}: {str(e)}")
    import traceback
    st.code(traceback.format_exc())
    st.warning("`amazon.py` not found. Using placeholder functions for demonstration.")
    def get_logo_base64():
        """Returns a base64 encoded string for a placeholder logo."""
        return "iVBORw0KGgoAAAANSUhEUgAAAQoAAAApCAYAAAD77MRbAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAHPSURBVHhe7dJBDQAgDAAxAbTj/ycqaKEtKEvcdDkHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADcsPTZfH/eAwbBGAwAYDAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgCAwQAAAAwGAACAwQAAAAwGAACAwQAAAAwGAACAwQAAAAwGAACAwQAAAAwGAACAwQAAAAwGAACAwQAAAAwGAACAwQAAAAwGAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAAAYDAAAMBgAAgMEAgMEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGBbfgAByAB2q0Bv/AAAAABJRU5ErkJggg=="

    def render_upload_tab():
        st.info("This is the placeholder for the CSV upload functionality.")
        st.file_uploader("Upload your Amazon CSV here", type=['csv'])

    def render_amazon_grid_tab():
        st.info("This is the placeholder for the Amazon Image Grid viewer.")
        st.write("Grid of images from Amazon would be displayed here.")

    def render_excel_grid_tab():
        st.warning("This tab is for Excel files with direct image URLs. Please use the Amazon Grid tab for Amazon products.")
        st.write("Grid of images from an Excel file would be displayed here.")
    AMAZON_AVAILABLE = True

# --- Main Application Code ---

# Encrypted Gemini API Keys (Secure)
ENCRYPTION_KEY = b's3Z36OOB8v2CxDQhFg90Ot3AMSxedH80xOrvehmz9h4='
ENCRYPTED_API_KEYS = 'Z0FBQUFBQm96S1RfLUdmTHc1MWgyOHpwRTRKSnNuZEhzQnY5YjJYZnFoYW5HVnFkWV9paGhtdWEwTVJoU3VNWnl4a2ExNlYxdHNMNnJEUGRKM2FJM0xSSFdlTWkwdnkxTVZVbVpxbm82VEZJYnNDSUlVbGRaeDdSMW90ZTEwczdRQTIxTDJ0emdLQWttSm0xTi1odU9RUDRTUlpaRFk2VldObklySzRQempteDVVMWZMTW41YXZmVm5iSkhJWTQ3RWtyaERxYUtBSzZlTUtDM0VCcGdxcE16d1pPTU1WQlRzTUdWRlJoM3pUUV92UmJuZFVidlBtN0R0aHhFT3E0NFZLYUN1ZjM3WWlRLXJCY0Z3VVJmLTAyQU1QTXZnYWZZeXE4TER6eG1IMVVzTXlnQ2F6eUdjM009'

def decrypt_gemini_keys():
    """Decrypt the Gemini API keys at runtime"""
    try:
        fernet = Fernet(ENCRYPTION_KEY)
        encrypted_keys = base64.b64decode(ENCRYPTED_API_KEYS.encode())
        decrypted_json = fernet.decrypt(encrypted_keys).decode()
        return json.loads(decrypted_json)
    except Exception as e:
        st.error(f"Failed to decrypt API keys: {str(e)}")
        return []

# Decrypt API keys at startup
GEMINI_API_KEYS = decrypt_gemini_keys()

# Page Configuration
st.set_page_config(
    page_title="Business Intelligence Suite",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Force sidebar to be expanded
if 'sidebar_state' not in st.session_state:
    st.session_state.sidebar_state = 'expanded'

# --- SIDEBAR RECOVERY CSS & EMERGENCY FIXES ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    :root {
        --font-family: 'Inter', sans-serif;
        --bg-color-main: #F8F9FA;
        --bg-color-card: #FFFFFF;
        --bg-color-dark-interactive: #1E1E1E;
        --text-color-dark: #212529;
        --text-color-dark-secondary: #6C757D;
        --text-color-light: #FFFFFF;
        --border-color-light: #E0E0E0;
        --primary-action-color: #FE4A49;
        --sidebar-bg: #121212;
        --sidebar-border: #333333;
        --info-bg: #E9F5FF;
        --info-border: #A6D7FF;
        --warning-bg: #FFFBEA;
        --warning-border: #FFE58A;
    }

    body, .stApp {
        font-family: var(--font-family);
        background-color: var(--bg-color-main) !important;
    }
    
    .main .block-container { padding: 1.5rem 3rem; }
    
    /* FIXED: Only hide specific menu items, not the sidebar toggle button */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    .stDeployButton { visibility: hidden; }
    
    /* FIXED: Ensure sidebar toggle button is visible - Multiple selectors for different Streamlit versions */
    button[kind="header"] { visibility: visible !important; }
    button[data-testid="collapsedControl"] { visibility: visible !important; }
    .css-1dp5vir { visibility: visible !important; }
    .css-16huue1 { visibility: visible !important; }
    header[data-testid="stHeader"] button { visibility: visible !important; }
    
    /* Force sidebar toggle to appear */
    .stApp > header, .stApp header[data-testid="stHeader"] {
        visibility: visible !important;
        display: block !important;
    }
    
    /* Emergency floating sidebar toggle */
    .floating-toggle {
        position: fixed !important;
        top: 10px !important;
        left: 10px !important;
        z-index: 9999 !important;
        background: #FE4A49 !important;
        color: white !important;
        border: none !important;
        padding: 8px 12px !important;
        border-radius: 6px !important;
        cursor: pointer !important;
        font-weight: bold !important;
        font-size: 16px !important;
    }
    
    /* Emergency sidebar visibility */
    section[data-testid="stSidebar"] {
        position: relative !important;
        display: block !important;
        visibility: visible !important;
    }
    
    section[data-testid="stSidebar"] {
        background-color: var(--sidebar-bg) !important;
        border-right: 1px solid var(--sidebar-border) !important;
    }
    .sidebar-title {
        font-size: 1.25rem; font-weight: 700; color: var(--text-color-light);
        text-align: center; padding: 1.5rem 1rem; margin-bottom: 1rem;
        background: #1E1E1E; border-radius: 12px;
        border: 1px solid var(--sidebar-border);
    }
    .section-header {
        font-size: 0.75rem; font-weight: 600; color: #CCCCCC !important;
        text-transform: uppercase; letter-spacing: 0.1em; margin: 1.5rem 0 0.5rem 0;
        padding-left: 0.5rem;
    }
    .stSidebar .stButton > button {
        width: 100%; text-align: left; background: #1E1E1E;
        border: 1px solid var(--sidebar-border); border-radius: 10px;
        padding: 0.875rem 1.25rem; margin-bottom: 0.5rem;
        font-family: var(--font-family); font-weight: 500; color: var(--text-color-light);
        transition: all 0.2s ease;
    }
    .stSidebar .stButton > button:hover { background: #2A2A2A; border-color: #4A4A4A; }
    
    .content-card {
        background: var(--bg-color-card);
        border: 1px solid var(--border-color-light);
        border-radius: 16px; padding: 2rem;
        margin-bottom: 2rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }
    .content-card .title {
        font-size: 1.75rem; font-weight: 700; color: var(--text-color-dark);
        margin-bottom: 0.5rem;
    }
    .content-card .subtitle {
        font-size: 1rem; color: var(--text-color-dark-secondary); font-weight: 400;
        line-height: 1.6;
    }

    /* FIXED: Input styling with proper placeholder colors */
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        border-radius: 10px !important; 
        border: 2px solid #E0E0E0 !important;
        padding: 0.75rem 1rem !important; 
        font-family: var(--font-family) !important;
        background: #FFFFFF !important;
        color: #212529 !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }
    
    /* FIXED: White placeholder text for password input */
    .stTextInput > div > div > input::placeholder {
        color: #888888 !important;
        opacity: 1 !important;
    }
    
    /* FIXED: Focus states for inputs */
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus {
        border-color: var(--primary-action-color) !important;
        box-shadow: 0 0 0 3px rgba(254, 74, 73, 0.1) !important;
        outline: none !important;
    }

    .stButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        border-radius: 10px !important; 
        border: 1px solid var(--bg-color-dark-interactive) !important;
        padding: 0.75rem 1rem !important; 
        font-family: var(--font-family) !important;
        background: var(--bg-color-dark-interactive) !important;
        color: var(--text-color-light) !important; 
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover,
    div[data-testid="stFormSubmitButton"] > button:hover {
        opacity: 0.85; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    div[data-testid="stFormSubmitButton"] > button.st-emotion-cache-19rxjzo {
        background: var(--primary-action-color) !important;
        border-color: var(--primary-action-color) !important;
    }
    
    /* FIXED: Label colors for better visibility */
    .stTextInput > label, .stNumberInput > label {
        color: var(--text-color-dark) !important; 
        font-weight: 600 !important;
        font-size: 0.9rem !important;
    }
    
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background: transparent; border: 1px solid var(--border-color-light);
        border-radius: 10px; padding: 0.75rem 1.5rem;
        font-weight: 600; color: var(--text-color-dark-secondary);
        transition: all 0.2s ease;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #F0F0F0; color: var(--text-color-dark);
        border-color: #A0A0A0;
    }
    .stTabs [aria-selected="true"] {
        background: var(--bg-color-dark-interactive) !important;
        color: var(--text-color-light) !important;
        border-color: var(--bg-color-dark-interactive) !important;
    }

    /* FIXED: Alert styling with better text contrast */
    div[data-testid="stAlert"] {
        border-radius: 12px; border-width: 1px; border-style: solid;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
    }
    div[data-testid="stAlert"] p { 
        color: #333 !important; 
        font-weight: 500 !important;
    }
    div[data-testid="stAlert"][kind="info"] {
        background-color: var(--info-bg); border-color: var(--info-border);
    }
    div[data-testid="stAlert"][kind="warning"] {
        background-color: var(--warning-bg); border-color: var(--warning-border);
    }
    
    .main-header-card {
        text-align: center; background: #fff; padding: 2rem; border-radius: 16px;
        border: 1px solid var(--border-color-light); margin-bottom: 2rem;
    }
    .main-header-card h1 { 
        font-size: 2.25rem; font-weight: 800; color: #212529; 
    }
    .main-header-card p { 
        font-size: 1.1rem; color: #6C757D; margin-bottom: 1.5rem; 
    }
    .enterprise-badge {
        display: inline-block; background-color: #28a745; color: white;
        padding: 0.4rem 0.9rem; font-size: 0.8rem; font-weight: 700;
        border-radius: 50px; text-transform: uppercase; letter-spacing: 0.5px;
    }
    .feature-card {
        background: #fff; border: 1px solid var(--border-color-light);
        border-radius: 16px; padding: 2rem; height: 100%;
        transition: all 0.2s ease-in-out;
    }
    .feature-card:hover { 
        transform: translateY(-5px); 
        box-shadow: 0 8px 20px rgba(0,0,0,0.08); 
    }
    .feature-card-title { 
        font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; 
        color: var(--text-color-dark); 
    }
    .feature-card-content { 
        font-size: 0.95rem; color: var(--text-color-dark-secondary); 
        line-height: 1.6; 
    }
    .border-blue { border-top: 4px solid #4A90E2; }
    .border-purple { border-top: 4px solid #9013FE; }
    .border-orange { border-top: 4px solid #F5A623; }
    
    /* FIXED: Ensure all text in main content area is readable */
    .main p, .main span, .main div {
        color: var(--text-color-dark) !important;
    }
    
    /* FIXED: Dataframe text visibility */
    .stDataFrame {
        color: var(--text-color-dark) !important;
    }
</style>
""", unsafe_allow_html=True)

# Emergency CSS fix and floating toggle button
st.markdown("""
<style>
.stApp > header { display: block !important; visibility: visible !important; }
section[data-testid="stSidebar"] { display: block !important; }
</style>

<div style="position: fixed; top: 10px; right: 10px; background: #333; color: white; padding: 8px 12px; border-radius: 6px; font-size: 12px; z-index: 999;">
    Press <strong>[</strong> key to toggle sidebar
</div>

<button class="floating-toggle" onclick="
    const sidebar = document.querySelector('[data-testid=\\'stSidebar\\']');
    if (sidebar) {
        sidebar.style.display = sidebar.style.display === 'none' ? 'block' : 'none';
    }
">☰</button>

<script>
// Check if sidebar is visible
function checkSidebar() {
    const sidebar = document.querySelector('[data-testid=\"stSidebar\"]');
    if (!sidebar || sidebar.style.display === 'none' || sidebar.offsetWidth === 0) {
        const recoveryDiv = document.getElementById('sidebar-recovery');
        if (recoveryDiv) {
            recoveryDiv.style.display = 'block';
        }
    }
}
setTimeout(checkSidebar, 1000);
</script>

<div id="sidebar-recovery" style="display: none; position: fixed; top: 50px; left: 10px; background: #FE4A49; color: white; padding: 12px; border-radius: 8px; z-index: 1000; font-weight: bold;">
    Sidebar hidden? Press <strong>[</strong> key or refresh page (F5)
</div>
""", unsafe_allow_html=True)

# Session State Management
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'current_view' not in st.session_state:
    st.session_state.current_view = 'home'
if 'is_scraping' not in st.session_state:
    st.session_state.is_scraping = False
if 'results_df' not in st.session_state:
    st.session_state.results_df = pd.DataFrame()
if 'scraper_instance' not in st.session_state:
    st.session_state.scraper_instance = None
if 'sidebar_visible' not in st.session_state:
    st.session_state.sidebar_visible = True

# Amazon session states
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

# --- Helper Functions ---
def show_login_page():
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown(f"""
        <div style="text-align: center; padding-top: 4rem;">
            <div style="background: #ffffff; border-radius: 12px; padding: 1rem; margin-bottom: 1.5rem; display: inline-block; border: 1px solid #E0E0E0;">
                <img src="data:image/png;base64,{get_logo_base64()}" style="max-width: 250px; height: auto;" alt="Logo">
            </div>
            <h1 style="color: #212529; font-size: 2rem; font-weight: 800;">Business Intelligence Suite</h1>
            <p style="color: #6C757D; font-size: 1rem; margin-bottom: 2rem;">Secure Access Portal</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.container():
            st.markdown("""
            <div class="content-card" style="padding: 2.5rem;">
                <div style="text-align: center; margin-bottom: 1.5rem;">
                    <h3 style="color: #212529; font-weight: 600;">🔐 Secure Login</h3>
                    <p style="color: #6C757D; font-size: 0.9rem;">Enter your credentials to access the dashboard</p>
                </div>
            """, unsafe_allow_html=True)

            with st.form("login_form"):
                password = st.text_input("🔑 Password", type="password", placeholder="Enter your password", label_visibility="collapsed")
                st.markdown("<br>", unsafe_allow_html=True)
                login_button = st.form_submit_button("Login to Dashboard", use_container_width=True, type="primary")
                
                if login_button:
                    if password == "nick123":
                        st.session_state.authenticated = True
                        st.success("Login successful! Welcome.")
                        st.rerun()
                    else:
                        st.error("Invalid credentials. Please try again.")
            st.markdown("</div>", unsafe_allow_html=True)

def create_page_header(title, subtitle, icon=""):
    st.markdown(f"""
    <div class="content-card">
        <h1 class="title">{icon} {title}</h1>
        <p class="subtitle">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)

def to_excel(df: pd.DataFrame, site_name: str):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Auction Data')
        if not df.empty and 'Recovery' in df.columns:
            percentages = [float(str(r).replace('%', '')) for r in df['Recovery'] if str(r).replace('%', '').replace('.', '', 1).isdigit()]
            if percentages:
                summary_data = [
                    ['Total Items', len(df)],
                    ['Average Recovery', f"{statistics.mean(percentages):.2f}%"],
                    ['Highest Recovery', f"{max(percentages):.2f}%"],
                    ['Lowest Recovery', f"{min(percentages):.2f}%"],
                    ['Export Date', datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                    ['Site', site_name]
                ]
                summary_df = pd.DataFrame(summary_data, columns=['Metric', 'Value'])
                summary_df.to_excel(writer, index=False, sheet_name='Summary')
    return output.getvalue()

def stop_scraping():
    if st.session_state.scraper_instance:
        st.session_state.scraper_instance.stop()
    st.session_state.is_scraping = False
    st.session_state.scraper_instance = None

def display_results(site_name):
    if not st.session_state.results_df.empty:
        st.markdown("---")
        st.subheader(f"📊 {site_name} Scraping Results")
        st.dataframe(st.session_state.results_df, use_container_width=True)
        excel_data = to_excel(st.session_state.results_df, site_name)
        st.download_button(
            label=f"Download Results as Excel",
            data=excel_data,
            file_name=f"{site_name.replace('.', '')}_data_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

def create_scraper_ui(site_name, placeholder_url, is_ai=False, special_note=None):
    if is_ai:
        create_page_header(f"{site_name} AI-Powered Auction Scraper", "Uses Google Gemini AI to find retail prices from product images", icon="🤖")
    else:
        create_page_header(f"{site_name} Direct Price Scraper", "No AI needed - uses existing retail price data from the site", icon="📊")

    if special_note:
        st.warning(f"💡 {special_note}")

    with st.form(key=f'{site_name}_form'):
        url = st.text_input("🔗 Auction URL", placeholder=placeholder_url, key=f'url_{site_name}')
        col1, col2 = st.columns(2)
        start_page = col1.number_input("📄 Start Page", min_value=1, value=1, step=1, key=f'start_{site_name}')
        end_page = col2.number_input("🔚 End Page (0 for no limit)", min_value=0, value=0, step=1, key=f'end_{site_name}')
        
        if is_ai:
            st.info("ℹ️ AI-powered price detection is enabled with built-in Gemini API keys.")
        
        submitted = st.form_submit_button(
            f"🚀 Start {site_name} Scraping", use_container_width=True, disabled=st.session_state.is_scraping
        )
    return submitted, url, start_page, end_page

def run_scraper(site_name, url, start_page, end_page, requires_ai=True):
    if not url:
        st.error("Please enter a valid URL.")
        return
    
    st.session_state.is_scraping = True
    st.session_state.results_df = pd.DataFrame()

    status_placeholder = st.empty()
    progress_placeholder = st.empty()
    metric_cols = st.columns(3)
    pages_metric, lots_metric, recovery_metric = metric_cols[0].empty(), metric_cols[1].empty(), metric_cols[2].empty()
    dataframe_placeholder = st.empty()
    
    pages_metric.metric("Pages Scraped", 0)
    lots_metric.metric("Lots Scraped", 0)
    recovery_metric.metric("Average Recovery", "0%")
    progress_placeholder.progress(0)
    
    ui_placeholders = {
        'status': status_placeholder, 'progress': progress_placeholder, 'dataframe': dataframe_placeholder,
        'metrics': {'pages': pages_metric, 'lots': lots_metric, 'recovery': recovery_metric}
    }
    
    scraper_api_keys = GEMINI_API_KEYS if requires_ai else []
    st.session_state.scraper_instance = AuctionScraper(gemini_api_keys=scraper_api_keys, ui_placeholders=ui_placeholders)
    
    try:
        results = st.session_state.scraper_instance.run(site_name, url, start_page, end_page)
        st.session_state.results_df = pd.DataFrame(results) if results else pd.DataFrame()
        if st.session_state.scraper_instance._is_running: # Check if it wasn't stopped
            status_placeholder.success(f"Scraping complete! Found {len(results)} items.")
    except Exception as e:
        status_placeholder.error(f"An error occurred during scraping: {str(e)}")
    
    st.session_state.is_scraping = False
    st.rerun()

def show_welcome():
    # Main Header Card
    st.markdown(f"""
    <div class="main-header-card">
        <img src="data:image/png;base64,{get_logo_base64()}" style="max-width: 250px; height: auto; margin-bottom: 1.5rem;" alt="Logo">
        <h1>Business Intelligence Suite</h1>
        <p>Advanced Data Analytics & Automation Platform</p>
        <span class="enterprise-badge">NextGen Enterprise Edition</span>
    </div>
    """, unsafe_allow_html=True)

    # Dashboard Info Card
    create_page_header(
        "Business Intelligence Dashboard", 
        "🎯 Comprehensive data collection and analysis tools for auction sites and e-commerce platforms. <br> 📊 Select a tool from the navigation panel to begin your analysis.",
        icon=" "
    )

    # Feature Cards
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="feature-card border-blue">
            <h3 class="feature-card-title">🤖 AI-Powered Auction Analytics</h3>
            <p class="feature-card-content">
                Advanced scraping for HiBid, BiddingKings, and BidLlama with integrated AI price detection.
            </p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class="feature-card border-purple">
            <h3 class="feature-card-title">⚡ Direct Market Intelligence</h3>
            <p class="feature-card-content">
                Real-time data extraction from 8 major auction platforms with built-in recovery analytics.
            </p>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class="feature-card border-orange">
            <h3 class="feature-card-title">📦 Product Image Management</h3>
            <p class="feature-card-content">
                Professional-grade CSV processing and image visualization tools for Amazon product catalogs.
            </p>
        </div>
        """, unsafe_allow_html=True)

def show_amazon_environment():
    if not AMAZON_AVAILABLE:
        st.error("❌ Amazon functionality not available because amazon.py is missing.")
        return
    
    create_page_header("Amazon Product Image Viewer", "Upload and manage product image catalogs with advanced grid visualization", icon="📦")
    
    tab1, tab2, tab3 = st.tabs(["📤 Upload CSV", "📦 Amazon Grid Images", "📋 Excel Grid Images"])
    with tab1:
        render_upload_tab()
    with tab2:
        render_amazon_grid_tab()
    with tab3:
        render_excel_grid_tab()

# --- Main App Logic ---
if not st.session_state.authenticated:
    show_login_page()
else:
    # === SIDEBAR RECOVERY SOLUTIONS ===
    
    # Emergency Sidebar Toggle Button (Only show when sidebar might be hidden)
    col1, col2, col3 = st.columns([1, 8, 1])
    with col1:
        if st.button("☰", help="Toggle Sidebar", key="sidebar_toggle"):
            st.session_state.sidebar_visible = not st.session_state.sidebar_visible
            st.rerun()

    # Show navigation help for non-home views
    if st.session_state.current_view != 'home':
        with st.expander("🔧 Navigation Help", expanded=False):
            st.markdown("""
            **If sidebar disappeared:**
            - Press `[` key (left bracket) to toggle sidebar
            - Refresh page with `F5` or `Ctrl+R`
            - Click the ☰ button (if visible)
            - Use the navigation buttons below as backup
            """)
            
            # Backup navigation buttons
            st.markdown("**Quick Navigation:**")
            nav_col1, nav_col2, nav_col3, nav_col4 = st.columns(4)
            
            with nav_col1:
                if st.button("🏠 Home", key="backup_home"):
                    st.session_state.current_view = 'home'
                    st.rerun()
            
            with nav_col2:
                if st.button("🤖 AI Scrapers", key="backup_ai"):
                    st.session_state.current_view = 'hibid'
                    st.rerun()
            
            with nav_col3:
                if st.button("📊 Direct Scrapers", key="backup_direct"):
                    st.session_state.current_view = 'nellis'
                    st.rerun()
                    
            with nav_col4:
                if st.button("📦 Amazon Tool", key="backup_amazon"):
                    st.session_state.current_view = 'amazon'
                    st.rerun()

    with st.sidebar:
        st.markdown('<div class="sidebar-title">NextGen Business Intelligence</div>', unsafe_allow_html=True)
        if st.button("🏠 Dashboard", key="home_btn", use_container_width=True): st.session_state.current_view = 'home'; st.rerun()
        if AMAZON_AVAILABLE and st.button("📦 Amazon Product Viewer", key="amazon_btn", use_container_width=True): st.session_state.current_view = 'amazon'; st.rerun()
        
        st.markdown('<div class="section-header">🤖 AI AUCTION SCRAPERS</div>', unsafe_allow_html=True)
        if st.button("🎯 HiBid Scraper", key="hibid_btn", use_container_width=True): st.session_state.current_view = 'hibid'; st.rerun()
        if st.button("👑 BiddingKings Scraper", key="biddingkings_btn", use_container_width=True): st.session_state.current_view = 'biddingkings'; st.rerun()
        if st.button("🦙 BidLlama Scraper", key="bidllama_btn", use_container_width=True): st.session_state.current_view = 'bidllama'; st.rerun()

        st.markdown('<div class="section-header">📊 DIRECT PRICE SCRAPERS</div>', unsafe_allow_html=True)
        if st.button("🏛️ Nellis Scraper", key="nellis_btn", use_container_width=True): st.session_state.current_view = 'nellis'; st.rerun()
        if st.button("🎪 BidFTA Scraper", key="bidfta_btn", use_container_width=True): st.session_state.current_view = 'bidfta'; st.rerun()
        if st.button("🏢 MAC.bid Scraper", key="macbid_btn", use_container_width=True): st.session_state.current_view = 'macbid'; st.rerun()
        if st.button("📈 A-Stock Scraper", key="astock_btn", use_container_width=True): st.session_state.current_view = 'astock'; st.rerun()
        if st.button("🎰 702Auctions Scraper", key="702auctions_btn", use_container_width=True): st.session_state.current_view = '702auctions'; st.rerun()
        if st.button("🌄 Vista Scraper", key="vista_btn", use_container_width=True): st.session_state.current_view = 'vista'; st.rerun()
        if st.button("💎 BidSoflo Scraper", key="bidsoflo_btn", use_container_width=True): st.session_state.current_view = 'bidsoflo'; st.rerun()
        if st.button("🛒 BidAuctionDepot Scraper", key="bidauctiondepot_btn", use_container_width=True): st.session_state.current_view = 'bidauctiondepot'; st.rerun()
            
        st.markdown('<hr style="margin: 2rem 0; border-color: var(--sidebar-border);">', unsafe_allow_html=True)
        if st.button("🚪 Logout", key="logout_btn", use_container_width=True): st.session_state.authenticated = False; st.session_state.current_view = 'home'; st.rerun()

    # --- Page/View Router ---
    view = st.session_state.current_view
    view_name_map = {
        'hibid': 'HiBid', 'biddingkings': 'BiddingKings', 'bidllama': 'BidLlama',
        'nellis': 'Nellis', 'bidfta': 'BidFTA', 'macbid': 'MAC.bid', 'astock': 'A-Stock',
        '702auctions': '702Auctions', 'vista': 'Vista', 'bidsoflo': 'BidSoflo',
        'bidauctiondepot': 'BidAuctionDepot'
    }

    if view == 'home': 
        show_welcome()
    elif view == 'amazon': 
        show_amazon_environment()
    elif view in view_name_map:
        site_name = view_name_map[view]
        is_ai = view in ['hibid', 'biddingkings', 'bidllama']
        placeholder = f"Enter {site_name} auction URL..."
        
        special_note = None
        if view in ['702auctions', 'vista']:
            special_note = "Pages start from 0 internally. Use 'Start Page' input."
        
        submitted, url, start, end = create_scraper_ui(site_name, placeholder, is_ai=is_ai, special_note=special_note)
        
        if submitted: 
            run_scraper(site_name, url, start, end, requires_ai=is_ai)
        
        if st.session_state.is_scraping:
            st.button("🛑 Stop Scraping", on_click=stop_scraping, use_container_width=True)
        
        display_results(site_name)
