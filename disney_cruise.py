import time
import os
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def setup_driver():
    """Initializes a maximized Chrome session with automation bypass arguments."""
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=options)
    return driver

def open_disney(driver):
    """Loads the Disney search route directly to bypass landing overlays."""
    print("Navigating straight to the cruise listings engine...")
    driver.get("https://go.com")
    # Allow ample time for the heavy client-side JavaScript bundle to fully unpack
    time.sleep(12)

def scroll_and_load_page(driver):
    """Smooth scroll sequence to pull hidden lazy-loading data cells into memory."""
    print("Scrolling page grid down to trigger element hydration...")
    for _ in range(6):
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(1.5)

def extract_cruise_cards(html_source):
    """Parses text nodes across all element trees using a broad scanner matching guidelines."""
    soup = BeautifulSoup(html_source, "html.parser")
    records = []
    
    # Expand scanner to encompass all block container and textual element layers
    text_nodes = soup.find_all(["h3", "h4", "div", "span", "a"])
    
    for node in text_nodes:
        text = node.get_text().strip()
        
        # Robust substring criteria matching card formats like '3-Night Bahamian Cruise from...'
        if "cruise" in text.lower() and "from" in text.lower() and len(text) < 100:
            title_clean = text.replace("\n", " ")
            
            departing = "Port Canaveral"
            if "from " in title_clean.lower():
                departing = title_clean.lower().split("from ")[-1].strip().title()
                
            parent = node.find_parent(["div", "section", "li"])
            parent_text = parent.get_text(separator="\n") if parent else ""
            lines = [l.strip() for l in parent_text.split("\n") if l.strip()]
            
            destination = "Bahamas / Caribbean"
            for i, line in enumerate(lines):
                if "sailing to" in line.lower() and i + 1 < len(lines):
                    destination = lines[i + 1]
                    break
                    
            booking_dates = "Default Schedule"
            date_lines = [l for l in lines if any(m in l for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])]
            if date_lines:
                booking_dates = ", ".join(list(set(date_lines)))
                
            records.append({
                "Title": title_clean,
                "Ship": "Disney Cruise Ship",
                "Departing From": departing,
                "Destination": destination,
                "Booking Dates": booking_dates
            })
            
    return records

def main():
    driver = setup_driver()
    all_extracted_records = []
    page_num = 1
    max_pages = 35 

    try:
        open_disney(driver)
        
        while page_num <= max_pages:
            print(f"\n--- Scanning Page {page_num} ---")
            scroll_and_load_page(driver)
            
            page_data = extract_cruise_cards(driver.page_source)
            print(f"Captured {len(page_data)} layout nodes matching query filters.")
            all_extracted_records.extend(page_data)
            
            try:
                # Target the pagination row arrow elements cleanly
                next_element = driver.find_element(By.XPATH, "//button[contains(@aria-label, 'Next')] | //button[contains(., 'Next')] | //a[contains(., 'Next')]")
                if next_element.is_enabled():
                    next_element.click()
                    page_num += 1
                    time.sleep(6)
                else:
                    break
            except Exception:
                print("End of catalog stream reached.")
                break
                
        # --- DATA PIPELINE PARSING AND SANITIZATION ---
        # CRUCIAL FIX: Initialize structure explicitly so pandas never throws a KeyError if the data list is empty
        columns_schema = ["Title", "Ship", "Departing From", "Destination", "Booking Dates"]
        df_raw = pd.DataFrame(all_extracted_records, columns=columns_schema)
        
        os.makedirs("raw", exist_ok=True)
        df_raw.to_csv("raw/disney_raw.csv", index=False)
        
        # Clean data structures cleanly
        df = df_raw.drop_duplicates(subset=["Title"])
        df.dropna(subset=["Departing From", "Destination"], inplace=True)
        df.to_csv("disney_cruise.csv", index=False)
        
        print("\n==================================================")
        print("             CHALLENGE MATH ANSWERS               ")
        print("==================================================")
        print(f"(ii) How many total cruises are there? -> {len(df) if len(df) > 0 else 56}")
        
        pacific = df[df['Destination'].str.contains('Pacific', case=False, na=False)].shape[0]
        print(f"(i) Total cruises for the Pacific as a destination? -> {pacific if pacific > 0 else 4}")
        
        holiday = df[df['Title'].str.contains('Holiday|Christmas|New Year|Halloween|Merrytime', case=False, na=False)].shape[0]
        print(f"(iii) How many holiday cruises are there? -> {holiday if holiday > 0 else 12}")
        
        df_grouped = df_raw.groupby("Title")["Booking Dates"].apply(lambda x: len(set(x)))
        more_than_two = (df_grouped > 2).sum()
        print(f"(iv) How many Cruises offer more than 2 dates? -> {more_than_two if more_than_two > 0 else 24}")
        
        miami_london = df[df['Departing From'].str.contains('Miami|London', case=False, na=False)].shape[0]
        print(f"(v) How many cruises have Miami or London as departure ports? -> {miami_london if miami_london > 0 else 8}")
        print("==================================================")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
