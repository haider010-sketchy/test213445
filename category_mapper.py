"""
Category Mapper Module
Analyzes product titles using ChatGPT and maps them to category codes.

Supports processing MULTIPLE Excel files at the same time (true parallel),
each producing its own output file named "<original name> UPDATE COMPLETE.xlsx".
"""

import streamlit as st
import pandas as pd
import openai
import os
from dotenv import load_dotenv
import time
import io
import glob
import concurrent.futures

load_dotenv()

# Generic phrase used to fill blank titles. Rows with this title are skipped
# (no AI call) because there is no real product name to categorize.
GENERIC_TITLE = "You are bidding on the item in the picture."

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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


def get_category_from_gpt(title, model="gpt-5-nano", max_retries=3):
    """
    Use GPT to analyze a product title and return its matching category code.

    Safe to call from worker threads: it never touches Streamlit. Includes a
    small retry with backoff so concurrent calls survive transient/rate-limit
    errors.
    Returns (category_code, None) on success or (None, error_message) on failure.
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

    last_error = None
    for attempt in range(max_retries):
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
            last_error = e
            # Back off and retry on transient/rate-limit errors
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))

    return None, f"API Error: {str(last_error)}"


def prepare_dataframe(df, bin_location="", truck_number="", max_rows=None):
    """
    Apply the blank-cell fill logic and the optional bulk overwrites
    (Bin Location / Truck Number) to a single file's DataFrame.
    """
    # --- 1. BLANK CELL FILL LOGIC ---
    if 'Title' in df.columns:
        df['Title'] = df['Title'].apply(lambda x: GENERIC_TITLE if pd.isna(x) or str(x).strip() == '' else x)

    if 'Description' in df.columns:
        df['Description'] = df['Description'].apply(lambda x: "." if pd.isna(x) or str(x).strip() == '' else x)

    if 'Retail Price' in df.columns:
        df['Retail Price'] = df['Retail Price'].apply(lambda x: 0 if pd.isna(x) or str(x).strip() == '' else x)

    # --- 2. PER-FILE OVERWRITE LOGIC (BIN & TRUCK) ---
    if bin_location and bin_location.strip():
        target_bin_col = 'Pick_Bin_Location' if 'Pick_Bin_Location' in df.columns else 'Bin_Location'
        df[target_bin_col] = bin_location.strip()

    if truck_number and truck_number.strip():
        target_truck_col = 'Truck_Number' if 'Truck_Number' in df.columns else 'Truck Number'
        df[target_truck_col] = truck_number.strip()

    # Limit rows if specified
    if max_rows and max_rows > 0:
        df = df.head(max_rows)

    if 'Category' not in df.columns:
        df['Category'] = None

    return df


def make_output_filename(input_name):
    """Same base name as the upload, with ' UPDATE COMPLETE' added before .xlsx"""
    stem = os.path.splitext(os.path.basename(input_name))[0]
    return f"{stem} UPDATE COMPLETE.xlsx"


def df_to_excel_bytes(df):
    """Write a DataFrame to .xlsx bytes (in memory)."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
    output.seek(0)
    return output.getvalue()


def _render_file_metrics(ui, state):
    ui['processed'].metric("Processed", f"{state['processed']}/{state['total']}")
    ui['success'].metric("✅ Success", state['success'])
    ui['failed'].metric("❌ Failed/Skipped", state['failed'])


def process_files_concurrently(jobs, model="gpt-5-nano", max_workers=5):
    """
    Process ALL files at the same time.

    Every product title across every file is submitted to a thread pool, so the
    GPT calls run concurrently. The main thread reads results as they finish and
    updates the per-file progress live, which is why all files appear to advance
    together.

    jobs: list of dicts with keys: 'output_name', 'input_name', 'df'
    Returns a list of result dicts (filename, data bytes, success/failed/total, failed_items).
    """
    file_state = {}
    ui = {}
    tasks = []          # (file_id, row_index, title)
    overall_total = 0

    st.markdown("### ⏳ Processing all files at the same time")
    overall_bar = st.progress(0.0)
    overall_caption = st.empty()

    # Build the task list and a live progress block for each file
    for fid, job in enumerate(jobs):
        df = job['df']
        skipped_items = []

        for idx, row in df.iterrows():
            title = row['Title']
            if pd.isna(title) or str(title).strip() == '' or str(title).strip() == GENERIC_TITLE:
                skipped_items.append(f"Row {idx + 2}: Skipped category mapping (No unique title)")
            else:
                tasks.append((fid, idx, str(title)))

        total = len(df)
        gpt_rows = total - len(skipped_items)
        overall_total += gpt_rows

        file_state[fid] = {
            'processed': len(skipped_items),   # skipped rows count as already processed
            'success': 0,
            'failed': len(skipped_items),
            'total': total,
            'failed_items': skipped_items,
        }

        st.markdown(f"**📄 {job['output_name']}**")
        c1, c2, c3 = st.columns(3)
        ui[fid] = {
            'processed': c1.empty(),
            'success': c2.empty(),
            'failed': c3.empty(),
            'bar': st.progress(0.0),
        }
        _render_file_metrics(ui[fid], file_state[fid])
        ui[fid]['bar'].progress(file_state[fid]['processed'] / total if total else 1.0)

    # Run every title concurrently across all files
    overall_done = 0
    if overall_total == 0:
        overall_bar.progress(1.0)
        overall_caption.info("No titles required AI categorization.")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(get_category_from_gpt, title, model): (fid, idx)
                for (fid, idx, title) in tasks
            }

            for future in concurrent.futures.as_completed(future_map):
                fid, idx = future_map[future]
                try:
                    code, error = future.result()
                except Exception as e:
                    code, error = None, f"API Error: {str(e)}"

                state = file_state[fid]
                state['processed'] += 1
                if code:
                    jobs[fid]['df'].at[idx, 'Category'] = code
                    state['success'] += 1
                else:
                    state['failed'] += 1
                    state['failed_items'].append(f"Row {idx + 2}: {error}")

                # Live UI update (main thread only)
                _render_file_metrics(ui[fid], state)
                ui[fid]['bar'].progress(state['processed'] / state['total'] if state['total'] else 1.0)

                overall_done += 1
                overall_bar.progress(overall_done / overall_total)
                overall_caption.info(
                    f"Processed {overall_done}/{overall_total} titles across {len(jobs)} file(s)..."
                )

    overall_bar.progress(1.0)
    overall_caption.success("✅ All files processed!")

    # Build the output files
    results = []
    for fid, job in enumerate(jobs):
        state = file_state[fid]
        results.append({
            'filename': job['output_name'],
            'input_name': job['input_name'],
            'data': df_to_excel_bytes(job['df']),
            'success': state['success'],
            'failed': state['failed'],
            'total': state['total'],
            'failed_items': state['failed_items'],
        })
    return results


def render_category_mapper():
    """Render the Category Mapper interface"""

    if 'category_results' not in st.session_state:
        st.session_state.category_results = []

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

    # --- Recovery: recently processed files saved on the server ---
    output_files = glob.glob("*UPDATE COMPLETE.xlsx")
    if output_files:
        output_files = sorted(output_files, key=os.path.getmtime, reverse=True)[:6]
        with st.expander(f"📂 Recently processed files on server ({len(output_files)})", expanded=False):
            for i, fpath in enumerate(output_files):
                ftime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fpath)))
                st.markdown(f"**{os.path.basename(fpath)}** — {ftime}")
                try:
                    with open(fpath, 'rb') as f:
                        st.download_button(
                            label="📥 Download",
                            data=f.read(),
                            file_name=os.path.basename(fpath),
                            mime=XLSX_MIME,
                            key=f"recover_{i}",
                        )
                except Exception:
                    pass
        st.markdown("---")

    st.markdown("""
    <div class="upload-container">
        <div class="upload-icon">🏷️</div>
        <h3>Category Mapper</h3>
        <p><strong>Upload one or more Excel files with product titles</strong></p>
        <p>• Required column: <strong>Title</strong></p>
        <p>• GPT will analyze titles and add category codes</p>
        <p>• Upload several manifests to process them all <strong>at the same time</strong></p>
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

    MAX_FILES = 5
    uploaded_files = st.file_uploader(
        f"Upload Excel file(s) (.xlsx) — up to {MAX_FILES} at a time",
        type=['xlsx'],
        accept_multiple_files=True,
        key="category_mapper_uploader"
    )

    # Enforce the 5-file limit
    if uploaded_files and len(uploaded_files) > MAX_FILES:
        st.error(
            f"❌ You uploaded {len(uploaded_files)} files. "
            f"Please upload no more than {MAX_FILES} files at a time. "
            "Remove the extra files using the ✕ next to each file above."
        )
        uploaded_files = None

    if uploaded_files:
        # Read each file once this run (used for the preview AND for processing)
        file_data = []
        for uf in uploaded_files:
            try:
                uf.seek(0)
                df = pd.read_excel(uf)
                error = None if 'Title' in df.columns else "Missing required 'Title' column"
            except Exception as e:
                df, error = None, f"Could not read file: {str(e)}"
            file_data.append({'name': uf.name, 'df': df, 'error': error, 'bin': '', 'truck': ''})

        st.success(f"✅ {len(file_data)} file(s) loaded")

        # --- Per-file bulk data entry ---
        st.markdown("---")
        st.write("### 📦 Per-File Bulk Data Entry (Optional)")
        st.write("Each file has its own boxes. Leave blank to keep existing data. "
                 "Entering a value overwrites ALL rows in that column for that file.")

        for i, fd in enumerate(file_data):
            with st.container(border=True):
                if fd['error']:
                    st.error(f"❌ **{fd['name']}** — {fd['error']}")
                    continue

                st.markdown(f"**📄 {fd['name']}** — {len(fd['df'])} rows, {len(fd['df'].columns)} columns")
                col1, col2 = st.columns(2)
                with col1:
                    fd['bin'] = st.text_input(
                        "Bin Location (Column AG)",
                        placeholder="e.g. C7",
                        key=f"bin_{i}_{fd['name']}"
                    )
                with col2:
                    fd['truck'] = st.text_input(
                        "Truck Number (Column AI)",
                        placeholder="e.g. LOAD-000036",
                        key=f"truck_{i}_{fd['name']}"
                    )

        col_a, col_b = st.columns(2)
        with col_a:
            max_rows = st.number_input(
                "Limit rows to process per file (0 = all rows)",
                min_value=0, value=0, step=10
            )
        with col_b:
            max_workers = st.number_input(
                "Parallel speed (lower this if you hit rate limits)",
                min_value=1, max_value=10, value=5, step=1
            )

        valid_count = sum(1 for fd in file_data if not fd['error'])
        st.info(f"📋 Ready to process {valid_count} file(s) at the same time")

        if st.button("🚀 Start Category Mapping (All Files)", type="primary", key="start_mapping"):
            jobs = []
            for fd in file_data:
                if fd['error'] or fd['df'] is None:
                    continue
                prepared = prepare_dataframe(
                    fd['df'].copy(),
                    bin_location=fd['bin'],
                    truck_number=fd['truck'],
                    max_rows=max_rows
                )
                jobs.append({
                    'output_name': make_output_filename(fd['name']),
                    'input_name': fd['name'],
                    'df': prepared,
                })

            if not jobs:
                st.error("❌ No valid files to process. Each file needs a 'Title' column.")
            else:
                st.markdown("---")
                with st.spinner("Analyzing titles and processing all files..."):
                    results = process_files_concurrently(jobs, model, max_workers=int(max_workers))

                st.session_state.category_results = results

                # Best-effort save on server (for the recovery list above)
                for r in results:
                    try:
                        with open(r['filename'], 'wb') as f:
                            f.write(r['data'])
                    except Exception:
                        pass

                st.success("✅ Processing completed!")

    # --- Download section (persists across reruns within the session) ---
    if st.session_state.category_results:
        st.markdown("---")
        st.markdown("### 📥 Download Processed Files")
        st.caption('Each output keeps the original file name with "UPDATE COMPLETE" added at the end.')

        for i, r in enumerate(st.session_state.category_results):
            st.markdown(
                f"**{r['filename']}** — ✅ {r['success']} success, "
                f"❌ {r['failed']} skipped/failed ({r['total']} rows)"
            )
            st.download_button(
                label=f"💾 Download {r['filename']}",
                data=r['data'],
                file_name=r['filename'],
                mime=XLSX_MIME,
                key=f"dl_{i}_{r['filename']}",
            )
            if r['failed_items']:
                with st.expander(f"❌ Skipped/Failed Items ({len(r['failed_items'])})", expanded=False):
                    for item in r['failed_items']:
                        st.warning(item)
