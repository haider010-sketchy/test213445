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
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

def get_category_from_gpt(title, model="gpt-5-nano"):
    """
    Use GPT to analyze product title and return matching category code
    """
    if not OPENAI_API_KEY:
        return None, "OpenAI API key not configured"
    
    # Create mapping text for GPT
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
        
        # Validate response is a number and exists in mapping
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

def process_excel_with_categories(df, model="gpt-5-nano", max_rows=None):
    """
    Process Excel file and add category codes using GPT
    """
    # Check if Title column exists
    if 'Title' not in df.columns:
        return None, "Excel file must contain a 'Title' column"
    
    # Limit rows if specified
    if max_rows and max_rows > 0:
        df = df.head(max_rows)
    
    total_rows = len(df)
    
    # Create progress indicators - SINGLE PLACEHOLDERS
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Create metrics containers - REUSE SAME CONTAINERS
    col1, col2, col3 = st.columns(3)
    processed_metric = col1.empty()
    success_metric = col2.empty()
    failed_metric = col3.empty()
    
    # Initialize Category column if it doesn't exist
    if 'Category' not in df.columns:
        df['Category'] = None
    
    processed_count = 0
    success_count = 0
    failed_count = 0
    failed_items = []
    
    for index, row in df.iterrows():
        title = row['Title']
        
        if pd.isna(title) or str(title).strip() == '':
            failed_items.append(f"Row {index + 2}: No title")
            failed_count += 1
            continue
        
        # Update status - SAME LINE
        processed_count += 1
        status_text.info(f"Processing row {processed_count}/{total_rows}: {str(title)[:60]}...")
        
        # Get category from GPT
        category_code, error = get_category_from_gpt(title, model)
        
        if category_code:
            df.at[index, 'Category'] = category_code
            success_count += 1
        else:
            failed_items.append(f"Row {index + 2}: {error}")
            failed_count += 1
        
        # Update progress
        progress = processed_count / total_rows
        progress_bar.progress(progress)
        
        # Update metrics - REUSE SAME CONTAINERS
        processed_metric.metric("Processed", f"{processed_count}/{total_rows}")
        success_metric.metric("✅ Success", success_count)
        failed_metric.metric("❌ Failed", failed_count)
        
        # Small delay to avoid rate limiting
        time.sleep(0.5)
    
    # Complete
    progress_bar.progress(1.0)
    status_text.success(f"✅ Processing complete! {success_count} successful, {failed_count} failed")
    
    # Show failed items if any
    if failed_items:
        with st.expander(f"❌ Failed Items ({len(failed_items)})", expanded=False):
            for item in failed_items:
                st.warning(item)
    
    return df, None

def render_category_mapper():
    """Render the Category Mapper interface"""
    
    # FIXED CSS - BLACK TEXT EVERYWHERE, WHITE BUTTONS
    st.markdown("""
    <style>
    /* BLACK TEXT ON ALL MAIN CONTENT */
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] *,
    [data-testid="stText"],
    [data-testid="stText"] *,
    .main h1, .main h2, .main h3, .main h4,
    .main p, .main span, .main div,
    label, .stMarkdown {
        color: #000000 !important;
    }
    
    /* WHITE TEXT ON BUTTONS */
    button, button *, 
    [data-testid="stButton"] button,
    [data-testid="stButton"] button *,
    [data-testid="stDownloadButton"] button,
    [data-testid="stDownloadButton"] button * {
        color: #FFFFFF !important;
    }
    
    /* FILE UPLOADER WHITE TEXT */
    [data-testid="stFileUploadDropzone"],
    [data-testid="stFileUploadDropzone"] * {
        color: #FFFFFF !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="upload-container">
        <div class="upload-icon">🏷️</div>
        <h3>Category Mapper</h3>
        <p><strong>Upload Excel file with product titles</strong></p>
        <p>• Required column: <strong>Title</strong></p>
        <p>• GPT will analyze titles and add category codes</p>
        <p>• Category codes will be added/updated in the <strong>Category</strong> column</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Check if OpenAI API key is configured
    if not OPENAI_API_KEY:
        st.error("⚠️ OpenAI API key not found!")
        st.markdown("""
        ### Setup Instructions:
        1. Create a `.env` file in your project directory
        2. Add your OpenAI API key:
           ```
           OPENAI_API_KEY=your_api_key_here
           ```
        3. Restart the app
        """)
        st.info("Get your OpenAI API key from: https://platform.openai.com/api-keys")
        return
    
    # Model selection
    model_option = st.selectbox(
        "Select GPT Model",
        ["gpt-5-nano (Ultra-Fast & Cheapest)", "gpt-5-mini (Balanced)", "gpt-5 (Most Accurate)"],
        help="gpt-5-nano is recommended - ultra-fast for category mapping"
    )
    
    if "nano" in model_option:
        model = "gpt-5-nano"
    elif "mini" in model_option:
        model = "gpt-5-mini"
    else:
        model = "gpt-5"
    
    # File upload
    uploaded_file = st.file_uploader(
        "Upload Excel file (.xlsx)",
        type=['xlsx'],
        key="category_mapper_uploader"
    )
    
    # Row limit
    max_rows = st.number_input(
        "Limit rows to process (0 = all rows)",
        min_value=0,
        value=0,
        step=10,
        help="Process only first N rows for testing"
    )
    
    if uploaded_file is not None:
        try:
            # Read Excel file
            df = pd.read_excel(uploaded_file)
            
            # Show preview
            st.success(f"✅ File loaded: {len(df)} rows, {len(df.columns)} columns")
            
            if 'Title' not in df.columns:
                st.error("❌ Excel file must contain a 'Title' column!")
                st.write("**Columns found:**", list(df.columns))
                return
            
            # Show file info
            st.info(f"📋 Ready to process {len(df)} products with GPT-5 nano")
            
            # Show columns found
            st.write("**Columns in file:**", ", ".join(df.columns.tolist()[:10]))
            if len(df.columns) > 10:
                st.write(f"... and {len(df.columns) - 10} more columns")
            
            # Process button
            if st.button("🚀 Start Category Mapping", type="primary", key="start_mapping"):
                st.markdown("---")
                
                with st.spinner("Analyzing titles with GPT..."):
                    updated_df, error = process_excel_with_categories(df, model, max_rows)
                
                if error:
                    st.error(f"❌ Error: {error}")
                    return
                
                if updated_df is not None:
                    st.success("✅ Category mapping completed!")
                    
                    # Store in session state
                    st.session_state.category_mapped_df = updated_df
                    
                    # Download button - NO PREVIEW
                    st.markdown("---")
                    
                    # Convert to Excel
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        updated_df.to_excel(writer, index=False, sheet_name='Products')
                    output.seek(0)
                    
                    excel_data = output.getvalue()
                    filename = f"categorized_products_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
                    
                    # Auto-download trigger
                    st.markdown(f"""
                    <script>
                        const blob = new Blob([new Uint8Array({list(excel_data)})], {{type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = '{filename}';
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        document.body.removeChild(a);
                    </script>
                    """, unsafe_allow_html=True)
                    
                    st.download_button(
                        label="💾 Download Excel with Categories",
                        data=excel_data,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_categorized_excel"
                    )
        
        except Exception as e:
            st.error(f"Error reading file: {str(e)}")
            st.code(str(e))
