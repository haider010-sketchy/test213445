"""
Category Mapper Module
Analyzes product titles using ChatGPT and maps them to category codes
"""

import streamlit as st
import pandas as pd
import openai
import os
from dotenv import load_dotenv
import time
import io
import glob

load_dotenv()

# Category mapping dictionary
CATEGORY_MAPPING = {
    10976: "Appliances",
    10977: "Arts, Crafts & Sewing",
    10978: "Automotive",
    10979: "Baby Products",
    10980: "Beauty & Personal Care",
    10981: "Books",
    10982: "Cell Phones & Accessories",
    10983: "Clothing, Shoes & Jewelry",
    10984: "Electronics",
    10965: "General Merchandise",
    10985: "Grocery & Gourmet Food",
    10986: "Health, Household & Baby Care",
    10987: "Home & Kitchen",
    10988: "Industrial & Scientific",
    10989: "Lawn, Garden & Patio",
    10990: "Luggage & Travel Gear",
    10991: "Musical Instruments",
    10992: "Office Products",
    10993: "Pallets",
    10994: "Pet Supplies",
    10995: "Sports & Outdoors",
    10996: "Tools & Home Improvement",
    10997: "Toys & Games",
    10998: "Video Games",
    10999: "Watches"
}

# Initialize OpenAI API
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

def get_category_from_gpt(title, model="gpt-5-nano"):
    """
    Use GPT to analyze product title and return matching category code
    """
    if not OPENAI_API_KEY:
        return None, "OpenAI API key not configured"
    
    mapping_text = "\n".join([f"{code}: {name}" for code, name in CATEGORY_MAPPING.items()])
    
    prompt = f"""You are a product categorization expert. Analyze the following product title and return ONLY the category code number that best matches.

Available Categories:
{mapping_text}

Product Title: {title}

Instructions:
- Return ONLY the numeric category code (e.g., 10976)
- Choose the BEST matching category
- If multiple categories could fit, choose the most specific one
- Do NOT include any explanation, just the number

Category Code:"""

    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a product categorization expert. Return only numeric category codes."},
                {"role": "user", "content": prompt}
            ]
        )
        
        category_code = response.choices[0].message.content.strip()
        
        try:
            code = int(category_code)
            if code in CATEGORY_MAPPING:
                return code, None
            else:
                return None, f"Invalid category code: {code}"
        except ValueError:
            return None, f"GPT returned non-numeric value: {category_code}"
    
    except Exception as e:
        return None, f"API Error: {str(e)}"

def process_excel_with_categories(df, model="gpt-5-nano", max_rows=None, bin_location="", truck_number=""):
    """
    Process Excel file and add category codes using GPT
    """
    if 'Title' not in df.columns:
        return None, "Excel file must contain a 'Title' column"

    # --- 1. BLANK CELL FILL LOGIC ---
    if 'Title' in df.columns:
        df['Title'] = df['Title'].apply(lambda x: "You are bidding on the item in the picture." if pd.isna(x) or str(x).strip() == '' else x)
        
    if 'Description' in df.columns:
        df['Description'] = df['Description'].apply(lambda x: "." if pd.isna(x) or str(x).strip() == '' else x)
        
    if 'Retail Price' in df.columns:
        df['Retail Price'] = df['Retail Price'].apply(lambda x: 0 if pd.isna(x) or str(x).strip() == '' else x)
        
    # --- 2. GLOBAL OVERWRITE LOGIC (BIN & TRUCK) ---
    # If the user typed something in the Bin Location box, overwrite all rows
    if bin_location.strip():
        # Uses the exact header name from your screenshot for Column AG
        target_bin_col = 'Pick_Bin_Location' if 'Pick_Bin_Location' in df.columns else 'Bin_Location'
        df[target_bin_col] = bin_location.strip()
        
    # If the user typed something in the Truck Number box, overwrite all rows
    if truck_number.strip():
        # Uses the exact header name from your screenshot for Column AI
        target_truck_col = 'Truck_Number' if 'Truck_Number' in df.columns else 'Truck Number'
        df[target_truck_col] = truck_number.strip()
        
    # Limit rows if specified
    if max_rows and max_rows > 0:
        df = df.head(max_rows)
    
    total_rows = len(df)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    col1, col2, col3 = st.columns(3)
    processed_metric = col1.empty()
    success_metric = col2.empty()
    failed_metric = col3.empty()
    
    if 'Category' not in df.columns:
        df['Category'] = None
    
    processed_count = 0
    success_count = 0
    failed_count = 0
    failed_items = []
    
    for index, row in df.iterrows():
        title = row['Title']
        
        # Skip GPT API call if the title was auto-filled (since it's a generic phrase)
        if pd.isna(title) or str(title).strip() == '' or title == "You are bidding on the item in the picture.":
            failed_items.append(f"Row {index + 2}: Skipped category mapping (No unique title)")
            failed_count += 1
            processed_count += 1
            progress = processed_count / total_rows
            progress_bar.progress(progress)
            processed_metric.metric("Processed", f"{processed_count}/{total_rows}")
            failed_metric.metric("❌ Failed/Skipped", failed_count)
            continue
        
        processed_count += 1
        status_text.info(f"Processing row {processed_count}/{total_rows}: {str(title)[:60]}...")
        
        category_code, error = get_category_from_gpt(title, model)
        
        if category_code:
            df.at[index, 'Category'] = category_code
            success_count += 1
        else:
            failed_items.append(f"Row {index + 2}: {error}")
            failed_count += 1
        
        progress = processed_count / total_rows
        progress_bar.progress(progress)
        
        processed_metric.metric("Processed", f"{processed_count}/{total_rows}")
        success_metric.metric("✅ Success", success_count)
        failed_metric.metric("❌ Failed/Skipped", failed_count)
        
        time.sleep(0.5)
    
    progress_bar.progress(1.0)
    status_text.success(f"✅ Processing complete! {success_count} successful, {failed_count} skipped/failed")
    
    if failed_items:
        with st.expander(f"❌ Skipped/Failed Items ({len(failed_items)})", expanded=False):
            for item in failed_items:
                st.warning(item)
    
    return df, None

def render_category_mapper():
    """Render the Category Mapper interface"""
    
    st.markdown("""
    <style>
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stText"],
    [data-testid="stText"] *,
    .main h1, .main h2, .main h3, .main h4,
    .main p, .main span, .main div,
    label, .stMarkdown {
        color: #000000 !important;
    }
    
    button, button *, 
    [data-testid="stButton"] button,
    [data-testid="stButton"] button *,
    [data-testid="stDownloadButton"] button,
    [data-testid="stDownloadButton"] button * {
        color: #FFFFFF !important;
    }
    
    [data-testid="stFileUploadDropzone"],
    [data-testid="stFileUploadDropzone"] * {
        color: #FFFFFF !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    excel_files = glob.glob("categorized_products_*.xlsx")
    if excel_files:
        latest_file = max(excel_files, key=os.path.getmtime)
        file_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(latest_file)))
        
        st.success(f"🎉 Last processed file found: **{latest_file}** (Generated: {file_time})")
        
        with open(latest_file, 'rb') as f:
            st.download_button(
                label="📥 Download Last Processed File",
                data=f.read(),
                file_name=latest_file,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_last_file",
                type="primary"
            )
        st.markdown("---")
    
    st.markdown("""
    <div class="upload-container">
        <div class="upload-icon">🏷️</div>
        <h3>Category Mapper</h3>
        <p><strong>Upload Excel file with product titles</strong></p>
        <p>• Required column: <strong>Title</strong></p>
        <p>• GPT will analyze titles and add category codes</p>
    </div>
    """, unsafe_allow_html=True)
    
    if not OPENAI_API_KEY:
        st.error("⚠️ OpenAI API key not found!")
        return
    
    model_option = st.selectbox(
        "Select GPT Model",
        ["gpt-5-nano (Ultra-Fast & Cheapest)", "gpt-5-mini (Balanced)", "gpt-5 (Most Accurate)"]
    )
    
    if "nano" in model_option:
        model = "gpt-5-nano"
    elif "mini" in model_option:
        model = "gpt-5-mini"
    else:
        model = "gpt-5"
    
    uploaded_file = st.file_uploader(
        "Upload Excel file (.xlsx)",
        type=['xlsx'],
        key="category_mapper_uploader"
    )
    
    max_rows = st.number_input(
        "Limit rows to process (0 = all rows)",
        min_value=0, value=0, step=10
    )
    
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success(f"✅ File loaded: {len(df)} rows, {len(df.columns)} columns")
            
            if 'Title' not in df.columns:
                st.error("❌ Excel file must contain a 'Title' column!")
                return
            
            # --- GLOBAL OVERWRITE INPUT BOXES ---
            st.markdown("---")
            st.write("### 📦 Bulk Data Entry (Optional)")
            st.write("Leave blank to keep existing data. Entering a value here will overwrite ALL rows in that column.")
            
            col1, col2 = st.columns(2)
            with col1:
                input_bin_location = st.text_input("Bin Location (Column AG)", placeholder="e.g. C7")
            with col2:
                input_truck_number = st.text_input("Truck Number (Column AI)", placeholder="e.g. LOAD-000036")
            
            st.info(f"📋 Ready to process {len(df)} products")
            
            if st.button("🚀 Start Category Mapping", type="primary", key="start_mapping"):
                st.markdown("---")
                
                with st.spinner("Analyzing titles and processing data..."):
                    updated_df, error = process_excel_with_categories(
                        df, 
                        model, 
                        max_rows, 
                        bin_location=input_bin_location, 
                        truck_number=input_truck_number
                    )
                
                if error:
                    st.error(f"❌ Error: {error}")
                    return
                
                if updated_df is not None:
                    st.success("✅ Processing completed!")
                    st.session_state.category_mapped_df = updated_df
                    st.markdown("---")
                    
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        updated_df.to_excel(writer, index=False, sheet_name='Products')
                    output.seek(0)
                    
                    excel_data = output.getvalue()
                    filename = f"categorized_products_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
                    
                    try:
                        old_files = glob.glob("categorized_products_*.xlsx")
                        for old_file in old_files:
                            try:
                                os.remove(old_file)
                            except:
                                pass
                        with open(filename, 'wb') as f:
                            f.write(excel_data)
                        st.info(f"✅ File saved on server: {filename}")
                    except Exception as e:
                        st.warning(f"Could not save backup: {str(e)}")
                    
                    st.download_button(
                        label="💾 Download Processed Excel",
                        data=excel_data,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_categorized_excel"
                    )
        
        except Exception as e:
            st.error(f"Error reading file: {str(e)}")
