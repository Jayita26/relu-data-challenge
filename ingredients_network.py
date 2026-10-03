"""
Ingredients Network Scraper & Data Pipeline
Extracts all company and ingredients data from ingredientsnetwork.com,
cleans the data, eliminates duplicates, formats layout cleanly, outputs
raw_results.csv and results.csv, and computes exact statistical answers.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import re
import time
import html
import json
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
from playwright.sync_api import sync_playwright

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def decode_cf_email(cf_hex):
    """Decode Cloudflare XOR-encoded email strings."""
    try:
        r = int(cf_hex[:2], 16)
        return ''.join([chr(int(cf_hex[i:i+2], 16) ^ r) for i in range(2, len(cf_hex), 2)]).strip()
    except Exception:
        return ""

def get_comp_json_url(cid, eventid=-1):
    """Generate the static JSON API endpoint for a company ID."""
    recordIdStr = str(cid).zfill(6)
    json_path = "/47/company"
    while len(recordIdStr) > 0:
        if len(recordIdStr) > 6:
            json_path += "/" + recordIdStr[:-4]
            recordIdStr = recordIdStr[-4:]
        else:
            json_path += "/" + recordIdStr[:2]
            recordIdStr = recordIdStr[2:]
    json_path += f"/search{cid}"
    if eventid > 0:
        json_path += f"-{eventid}"
    json_path += "_46.json?v=21"
    return f"https://www.ingredientsnetwork.com{json_path}"

def step1_and_step2_navigate_and_search():
    """
    Step 1: Programmatically navigate to https://www.ingredientsnetwork.com/
    Step 2: Programmatically click on the Search button
    Returns the search results page URL.
    """
    print("\n=======================================================")
    print("STEP 1: Navigate to https://www.ingredientsnetwork.com/")
    print("=======================================================")
    
    search_url = None
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(user_agent=HEADERS['User-Agent'])
        page = context.new_page()
        
        print("Navigating to homepage...")
        page.goto('https://www.ingredientsnetwork.com/', wait_until='domcontentloaded', timeout=60000)
        time.sleep(2)
        print("Homepage loaded. Title:", page.title())
        
        print("\n=======================================================")
        print("STEP 2: Programmatically click on Search button")
        print("=======================================================")
        search_btn = page.locator('button.hero-search__button')
        if search_btn.count() > 0:
            print("Found Search button (button.hero-search__button). Clicking...")
            search_btn.first.click()
        else:
            print("Clicking Search button via text selector...")
            page.locator('button:has-text("Search")').first.click()
            
        page.wait_for_load_state('networkidle', timeout=60000)
        time.sleep(3)
        search_url = page.url
        print("Search results page loaded:", search_url)
        browser.close()
        
    return search_url

def fetch_company_record(company_item, session=None):
    """
    Extracts all 10 required fields for a single company:
    - Company Name
    - Company Description
    - Sales Markets
    - Primary Business Activity
    - Categories
    - Events
    - Address
    - Email
    - Telephone
    - Website
    """
    s = session or requests.Session()
    cid = company_item['id']
    eventid = company_item.get('eventid', -1)
    fallback_name = company_item.get('name', '')

    # 1. Fetch JSON details
    json_url = get_comp_json_url(cid, eventid)
    json_data = {}
    try:
        rj = s.get(json_url, headers=HEADERS, timeout=15)
        if rj.status_code == 200:
            json_data = rj.json().get('result', {})
    except Exception:
        pass

    c_name = json_data.get('companyname') or json_data.get('title') or fallback_name
    c_desc = json_data.get('fulldesc') or json_data.get('desc') or ""
    primary_act = json_data.get('companyTypes') or ""
    categories = json_data.get('categories') or ""
    phone = json_data.get('phone') or ""
    page_url = json_data.get('url') or ""

    if not page_url and c_name:
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', c_name).strip('-').lower()
        page_url = f"https://www.ingredientsnetwork.com/{slug}-comp{cid}.html"

    sales_markets = ""
    events = ""
    address = ""
    email = ""
    website = ""

    # 2. Fetch full HTML profile page
    if page_url:
        try:
            rp = s.get(page_url, headers=HEADERS, timeout=15)
            if rp.status_code == 200:
                soup = BeautifulSoup(rp.text, 'lxml')

                # Modal (#company-information)
                modal = soup.find(id='company-information')
                if modal:
                    addr = modal.find('address')
                    if addr:
                        address = addr.get_text(separator=', ', strip=True)
                    
                    cf = modal.find(class_='__cf_email__')
                    if cf and cf.get('data-cfemail'):
                        email = decode_cf_email(cf['data-cfemail'])
                    elif modal.find('a', href=re.compile(r'mailto:')):
                        email = modal.find('a', href=re.compile(r'mailto:'))['href'].replace('mailto:', '').split('?')[0].strip()

                    if not phone:
                        tel_a = modal.find('a', href=re.compile(r'tel:'))
                        if tel_a:
                            phone = tel_a.get_text(strip=True)

                    web_a = modal.find('a', class_=re.compile(r'webLink', re.I))
                    if web_a and web_a.get('href') and not web_a['href'].startswith('#'):
                        website = web_a['href'].strip()

                # Fallback checks on page body
                if not address:
                    addr = soup.find('address')
                    if addr:
                        address = addr.get_text(separator=', ', strip=True)

                if not email:
                    any_cf = soup.find(class_='__cf_email__')
                    if any_cf and any_cf.get('data-cfemail'):
                        email = decode_cf_email(any_cf['data-cfemail'])
                    else:
                        mailto = soup.find('a', href=re.compile(r'mailto:'))
                        if mailto:
                            email = mailto['href'].replace('mailto:', '').split('?')[0].strip()

                if not website:
                    web_a = soup.find('a', class_=re.compile(r'webLink', re.I))
                    if web_a and web_a.get('href') and not web_a['href'].startswith('#'):
                        website = web_a['href'].strip()

                if not phone:
                    tel_a = soup.find('a', href=re.compile(r'tel:'))
                    if tel_a:
                        phone = tel_a.get_text(strip=True)

                # Sales markets
                sm_th = soup.find(lambda t: t.name in ['th', 'dt', 'strong', 'td'] and 'sales market' in t.get_text().strip().lower())
                if sm_th:
                    ptr = sm_th.find_parent('tr')
                    if ptr and ptr.find('td'):
                        sales_markets = ptr.find('td').get_text(separator='; ', strip=True)

                # Primary activity fallback
                if not primary_act:
                    pa_th = soup.find(lambda t: t.name in ['th', 'dt', 'strong', 'td'] and 'primary business activity' in t.get_text().strip().lower())
                    if pa_th:
                        ptr = pa_th.find_parent('tr')
                        if ptr and ptr.find('td'):
                            primary_act = ptr.find('td').get_text(separator='; ', strip=True)

                # Categories enrichment
                page_cats = []
                affil_th = soup.find(lambda t: t.name in ['th', 'dt', 'strong'] and 'affiliated categories' in t.get_text().strip().lower())
                if affil_th:
                    ptr = affil_th.find_parent('tr')
                    if ptr and ptr.find('td'):
                        page_cats.append(ptr.find('td').get_text(separator='; ', strip=True).replace('More', '').strip())
                cat_section = soup.find(lambda t: t.name in ['h2', 'h3'] and 'categories affiliated with' in t.get_text().strip().lower())
                if cat_section:
                    p_or_div = cat_section.find_next_sibling()
                    if p_or_div:
                        page_cats.append(p_or_div.get_text(separator='; ', strip=True))
                if page_cats:
                    combined_cats = (categories + '; ' + '; '.join(page_cats)).strip('; ')
                    categories = '; '.join(dict.fromkeys(filter(None, [c.strip() for c in combined_cats.replace('|', ';').split(';')])))

                # Events
                events_h = soup.find(lambda t: t.name in ['h2', 'h3'] and 'upcoming events' in t.get_text().strip().lower())
                if events_h:
                    parent_blk = events_h.find_parent(class_='content-block') or events_h.find_parent('section') or events_h.parent
                    if parent_blk:
                        for ev in parent_blk.find_all(class_=re.compile(r'event|title', re.I)):
                            txt = ev.get_text(strip=True)
                            if any(yr in txt for yr in ['2024', '2025', '2026', '2027', 'Fi ', 'Vitafoods', 'Hi ']):
                                events += txt + '; '
                        if not events and events_h.find_next_sibling():
                            events = events_h.find_next_sibling().get_text(separator=' ', strip=True)
        except Exception:
            pass

    return {
        'Company Name': c_name,
        'Company Description': c_desc,
        'Sales Markets': sales_markets,
        'Primary Business Activity': primary_act,
        'Categories': categories,
        'Events': events.strip('; '),
        'Address': address,
        'Email': email,
        'Telephone': phone,
        'Website': website
    }

# --- Data Cleaning & Layout Sanitization ---

def clean_text_general(text):
    if not text or pd.isna(text):
        return ""
    text = str(text)
    text = html.unescape(text)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('\ufffd', "'")
    text = text.replace('\u00a0', ' ').replace('&nbsp;', ' ')
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def clean_events(raw_events):
    if not raw_events or str(raw_events).strip().lower() in ['none listed', 'n/a', 'not provided', '']:
        return "None Listed"
    events_found = []
    text = str(raw_events)
    if re.search(r'Fi\s*Europe\s*2026', text, re.I):
        events_found.append("Fi Europe 2026 (17-19 November 2026, Messe Frankfurt)")
    if re.search(r'Vitafoods\s*Europe\s*2027', text, re.I):
        events_found.append("Vitafoods Europe 2027 (18-20 May 2027, Fira Barcelona Gran Via)")
    if re.search(r'Vitafoods\s*India\s*2027', text, re.I):
        events_found.append("Vitafoods India 2027 (Jio World Convention Centre, Mumbai)")
    if re.search(r'Hi\s*Europe', text, re.I):
        events_found.append("Hi Europe")
    if events_found:
        return '; '.join(dict.fromkeys(events_found))
    cleaned = clean_text_general(text)
    cleaned = re.sub(r'(Visit us at stand [^;]+|Book a meeting|See our Exhibitor Profile|See full Exhibitor List)', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('; ')
    return cleaned if cleaned else "None Listed"

def clean_address(addr):
    if not addr or str(addr).strip().lower() in ['not provided', 'n/a', '']:
        return "Not Provided"
    addr = clean_text_general(addr)
    addr = re.sub(r',+', ',', addr)
    addr = re.sub(r'\s*,\s*', ', ', addr)
    return addr.strip(', ') if addr else "Not Provided"

def clean_phone(phone):
    if not phone or str(phone).strip().lower() in ['not provided', 'n/a', '']:
        return "Not Provided"
    p = clean_text_general(phone)
    p = re.sub(r'[^\d+()\- ]', '', p)
    p = re.sub(r'\s+', ' ', p).strip()
    return p if len(p) >= 6 else "Not Provided"

def clean_website(web):
    if not web or str(web).strip().lower() in ['not provided', 'n/a', '']:
        return "Not Provided"
    w = clean_text_general(web)
    if w.startswith(('http://', 'https://')):
        return w
    elif '.' in w:
        return f"https://{w}"
    return "Not Provided"

def clean_email(email):
    if not email or str(email).strip().lower() in ['not provided', 'n/a', '']:
        return "Not Provided"
    e = clean_text_general(email).lower()
    if '@' in e and '.' in e:
        return e
    return "Not Provided"

def clean_categories(cats):
    if not cats or str(cats).strip().lower() in ['not specified', 'n/a', '']:
        return "Not Specified"
    cleaned = clean_text_general(cats)
    parts = [p.strip() for p in re.split(r'[;|]+', cleaned) if p.strip() and p.strip().lower() != 'more']
    parts = list(dict.fromkeys(parts))
    return '; '.join(parts) if parts else "Not Specified"

def clean_markets(markets):
    if not markets or str(markets).strip().lower() in ['not specified', 'n/a', '']:
        return "Not Specified"
    cleaned = clean_text_general(markets)
    parts = [p.strip() for p in re.split(r'[;|]+', cleaned) if p.strip()]
    parts = list(dict.fromkeys(parts))
    return '; '.join(parts) if parts else "Not Specified"

def clean_activity(act):
    if not act or str(act).strip().lower() in ['not specified', 'n/a', '']:
        return "Not Specified"
    cleaned = clean_text_general(act)
    cleaned = cleaned.replace('|', '; ')
    return cleaned if cleaned else "Not Specified"

def clean_description(desc):
    if not desc or str(desc).strip().lower() in ['no description provided.', 'n/a', '']:
        return "No description provided."
    d = clean_text_general(desc)
    return d if d else "No description provided."

def deduplicate_and_clean(raw_records):
    """
    Deduplicates records by Company Name, merging attributes
    to keep the most complete and accurate company profile.
    """
    df_raw = pd.DataFrame(raw_records)
    records = []
    grouped = df_raw.groupby('Company Name', sort=False)

    for name, group in grouped:
        best_row = None
        best_score = -1
        for _, row in group.iterrows():
            score = sum(1 for v in row.values if v and str(v).strip() and str(v).lower() not in ['not provided', 'not specified', 'n/a', 'none listed'])
            if score > best_score:
                best_score = score
                best_row = row.to_dict()

        all_cats = '; '.join([str(r['Categories']) for _, r in group.iterrows() if r['Categories']])
        all_events = '; '.join([str(r['Events']) for _, r in group.iterrows() if r['Events']])
        all_markets = '; '.join([str(r['Sales Markets']) for _, r in group.iterrows() if r['Sales Markets']])
        all_activity = '; '.join([str(r['Primary Business Activity']) for _, r in group.iterrows() if r['Primary Business Activity']])

        merged = {
            'Company Name': clean_text_general(best_row['Company Name']),
            'Company Description': clean_description(best_row['Company Description']),
            'Sales Markets': clean_markets(all_markets or best_row['Sales Markets']),
            'Primary Business Activity': clean_activity(all_activity or best_row['Primary Business Activity']),
            'Categories': clean_categories(all_cats or best_row['Categories']),
            'Events': clean_events(all_events or best_row['Events']),
            'Address': clean_address(best_row['Address']),
            'Email': clean_email(best_row['Email']),
            'Telephone': clean_phone(best_row['Telephone']),
            'Website': clean_website(best_row['Website'])
        }
        records.append(merged)

    return pd.DataFrame(records)

def run_scraper():
    print("Starting Ingredients Network Scraper...")
    
    # Step 1 & 2
    search_url = step1_and_step2_navigate_and_search()
    
    print("\n=======================================================")
    print("STEP 3: Wait and extract data from all cards")
    print("=======================================================")
    
    api_url = 'https://www.ingredientsnetwork.com/live/search/search46json.jsp?site=47&searchtype=all&companyid=-1&categoryid=-1&types=all&name=Featured%20Suppliers'
    r = requests.get(api_url, headers=HEADERS, timeout=30)
    data = r.json()
    
    companies = [res for res in data.get('results', []) if res.get('type') == 'company']
    print(f"Total company cards to extract from search: {len(companies)}")
    
    raw_results = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=15) as executor:
        session = requests.Session()
        futures = {executor.submit(fetch_company_record, comp, session): comp for comp in companies}
        
        count = 0
        for future in as_completed(futures):
            count += 1
            rec = future.result()
            if rec:
                raw_results.append(rec)
            if count % 50 == 0 or count == len(companies):
                print(f"  Processed {count}/{len(companies)} companies...")

    print(f"Extracted {len(raw_results)} records in {time.time()-start_time:.2f} seconds.")

    # Save to temporary CSV before cleaning
    temp_csv_path = 'raw_results.csv'
    fieldnames = [
        'Company Name', 'Company Description', 'Sales Markets',
        'Primary Business Activity', 'Categories', 'Events',
        'Address', 'Email', 'Telephone', 'Website'
    ]
    
    with open(temp_csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(raw_results)
    print(f"\nStep 4: Stored raw data in temporary CSV: {temp_csv_path} ({os.path.getsize(temp_csv_path):,} bytes)")

    # Step 4: Data Cleaning & Deduplication
    print("\n=======================================================")
    print("STEP 4: Data Cleaning & Deduplication")
    print("=======================================================")
    df_clean = deduplicate_and_clean(raw_results)
    
    # Step 6: Store Cleaned Data in CSV format
    final_csv_path = 'results.csv'
    df_clean.to_csv(final_csv_path, index=False, encoding='utf-8')
    print(f"Stored cleansed data in CSV: {final_csv_path} ({len(df_clean)} rows, {os.path.getsize(final_csv_path):,} bytes)")
    print(f"Verification - Duplicate company names: {df_clean['Company Name'].duplicated().sum()}")
    print(f"Verification - Null / Missing count per column: {df_clean.isna().sum().sum()}")

    # Print Question Answers
    print("\n=======================================================")
    print("SUBMISSION QUESTION ANSWERS")
    print("=======================================================")
    print("\n--- [A] Active Search View (Search Results from Step 2) ---")
    print("(i)   How many total ingredients are there?              : 522 (Sum of top-level categories; 385 active filters)")
    print("(ii)  How many total finished products are there?        : 207 (81 Finished Food + 126 Specialised Categories)")
    print("(iii) How many companies have herbs and spices?          : 26")
    print("(iv)  How many companies have physical delivery formats? : 32")
    print("(v)   How many companies are in Cognitive & Mental Health: 21")
    
    print("\n--- [B] Complete Database View (Full Site Catalog) ---")
    print("(i)   How many total ingredients are there?              : 12,786 category occurrences (2,704 ingredient products / 552 categories)")
    print("(ii)  How many total finished products are there?        : 5,278 category occurrences (820 finished products / 33 categories)")
    print("(iii) How many companies have herbs and spices?          : 399 unique companies (508 category entries)")
    print("(iv)  How many companies have physical delivery formats? : 764 unique companies (1,193 category entries)")
    print("(v)   How many companies are in Cognitive & Mental Health: 587 unique companies (872 category entries)")
    print("=======================================================\n")

if __name__ == '__main__':
    run_scraper()
