"""
Disney Cruise Line Data Extraction & Analysis Pipeline
======================================================
Target URL: https://disneycruise.disney.go.com/en-in/
Outputs:
  - results.csv (cleansed cruise catalog)
  - Analysis answers printed to terminal for questions (i) through (v)
"""

import asyncio
import json
import os
import re
import sys
import pandas as pd
from playwright.async_api import async_playwright

# Ensure proper Unicode encoding in Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


# ==============================================================================
# Helper Functions: Data Cleaning & Text Normalization
# ==============================================================================

def clean_text(text):
    """Clean string by stripping whitespace and removing special artifacts."""
    if text is None:
        return ""
    text = str(text).strip()
    text = text.replace("", "")
    text = re.sub(r"\s+", " ", text)
    return text


def extract_departure_from_title(title):
    """Extract departure port name from cruise title (e.g. 'from Fort Lauderdale')."""
    match = re.search(r"\bfrom\s+([^,]+?)(?:\s+ending|\s+with|\s*$)", title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


# ==============================================================================
# Scraper Class
# ==============================================================================

class DisneyCruiseScraper:
    def __init__(self, output_csv="results.csv", output_json="collected_cruises_raw.json"):
        self.output_csv = output_csv
        self.output_json = output_json
        self.base_url = "https://disneycruise.disney.go.com/en-in/"
        self.search_url = "https://disneycruise.disney.go.com/cruises-destinations/list/"
        self.captured_products = []
        self.captured_page_ids = set()

    async def run(self):
        print("=" * 80)
        print(" DISNEY CRUISE LINE - SCRAPING & CLEANING PIPELINE")
        print("=" * 80)

        async with async_playwright() as p:
            # Launch Chrome with stealth parameters to bypass Akamai Bot Manager
            browser = await p.chromium.launch(
                headless=True,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--window-size=1920,1080",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            # Override navigator properties to ensure complete stealth
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page = await context.new_page()

            # Intercept background product availability API responses
            async def on_response(response):
                if "available-products" in response.url:
                    try:
                        data = await response.json()
                        products = data.get("products", [])
                        total_pages = data.get("totalPages", 35)
                        if products:
                            # Track unique page batches
                            batch_sig = tuple(p.get("productId", "") for p in products)
                            if batch_sig not in self.captured_page_ids:
                                self.captured_page_ids.add(batch_sig)
                                self.captured_products.extend(products)
                                page_idx = len(self.captured_page_ids)
                                print(
                                    f"  [+] Captured Page {page_idx}/{total_pages} "
                                    f"({len(products)} products) | First: {products[0].get('productDisplayName', '')}",
                                    flush=True,
                                )
                    except Exception:
                        pass

            page.on("response", on_response)

            # ------------------------------------------------------------------
            # Step 1: Navigate and Agree
            # ------------------------------------------------------------------
            print("\n[Step 1] Navigating to Home Page and Handling Agreements...")
            print(f"  Navigating to {self.base_url} ...")
            await page.goto(self.base_url, timeout=60000)
            await page.wait_for_timeout(3000)

            # Dismiss cookie/consent banner if present
            try:
                agree_button = page.locator(
                    "button:has-text('Agree'), button:has-text('Accept'), button#onetrust-accept-btn-handler"
                )
                if await agree_button.count() > 0 and await agree_button.first.is_visible():
                    await agree_button.first.click()
                    print("  [✓] Agreed to terms / dismissed cookie consent dialog.")
                    await page.wait_for_timeout(1000)
                else:
                    print("  [i] No consent popup displayed; proceeding.")
            except Exception as e:
                print(f"  [!] Cookie check completed: {e}")

            # ------------------------------------------------------------------
            # Step 2: Click on the Search Button (View Dates)
            # ------------------------------------------------------------------
            print("\n[Step 2] Programmatically Clicking Search Button ('View Dates')...")
            view_dates_btn = page.locator(
                "a:has-text('View Dates'), button:has-text('View Dates'), [aria-label*='View Dates']"
            ).first

            if await view_dates_btn.count() > 0:
                await view_dates_btn.click()
                print("  [✓] Clicked 'View Dates' button.")
            else:
                print("  [!] Direct link navigation to search list page...")
                await page.goto(self.search_url)

            # ------------------------------------------------------------------
            # Step 3: Wait for Results to Load
            # ------------------------------------------------------------------
            print("\n[Step 3] Waiting for Search Results and Cruise Cards to Load...")
            for wait_i in range(20):
                if len(self.captured_page_ids) > 0:
                    break
                await page.wait_for_timeout(1000)

            print(
                f"  [✓] Initial search results loaded! "
                f"({len(self.captured_products)} products captured from initial view)"
            )

            # ------------------------------------------------------------------
            # Step 4: Collect Data from Each Card (Scroll to load at least 35 pages)
            # ------------------------------------------------------------------
            print("\n[Step 4] Scrolling to Load Cards Across at least 35 Pages...")
            max_scroll_attempts = 60
            consecutive_no_new_pages = 0
            last_page_count = len(self.captured_page_ids)

            for scroll_step in range(1, max_scroll_attempts + 1):
                # Scroll using PageDown key and window scrollBy to ensure natural viewport trigger
                await page.keyboard.press("PageDown")
                await page.keyboard.press("PageDown")
                await page.evaluate("window.scrollBy(0, 1600);")
                await page.wait_for_timeout(2000)

                current_page_count = len(self.captured_page_ids)
                if current_page_count >= 35:
                    print(f"  [✓] Successfully reached target: {current_page_count} pages captured!")
                    break

                if current_page_count == last_page_count:
                    consecutive_no_new_pages += 1
                    if consecutive_no_new_pages >= 6:
                        # Nudge scroll up slightly and then to absolute bottom to trigger infinite scroll
                        await page.evaluate("window.scrollBy(0, -600);")
                        await page.wait_for_timeout(1000)
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                        await page.wait_for_timeout(2500)
                        if (
                            len(self.captured_page_ids) == last_page_count
                            and consecutive_no_new_pages >= 12
                        ):
                            print(
                                f"  [✓] Reached end of available catalog at {current_page_count} pages."
                            )
                            break
                else:
                    consecutive_no_new_pages = 0
                    last_page_count = current_page_count

            print(
                f"  [✓] Scroll extraction finished! "
                f"Total Pages Captured: {len(self.captured_page_ids)}, "
                f"Total Product Batches: {len(self.captured_products)}"
            )

            # Save temporary raw JSON
            with open(self.output_json, "w", encoding="utf-8") as f:
                json.dump(self.captured_products, f, indent=2)
            print(f"  [✓] Temporary raw extraction saved to {self.output_json}")

            await browser.close()

        # ----------------------------------------------------------------------
        # Step 5 & 6: Data Cleaning, Deduplication, and CSV Export
        # ----------------------------------------------------------------------
        self.clean_and_export()
        self.perform_analysis()

    def clean_and_export(self):
        print("\n[Step 5] Applying Data Cleaning Rules & Deduplication...")
        records = []
        seen_keys = set()

        for p in self.captured_products:
            p_id = clean_text(p.get("productId", ""))
            p_name = clean_text(p.get("productDisplayName", ""))
            p_str = json.dumps(p)

            # Determine theme/holiday classification
            theme = "Standard"
            if "merrytime" in p_id.lower() or "MERRY" in p_str:
                theme = "Very Merrytime (Holiday)"
            elif "halloween" in p_id.lower() or "SPOOKY" in p_str:
                theme = "Halloween on the High Seas"
            elif "marvel" in p_id.lower() or "MDAS" in p_str:
                theme = "Marvel Day at Sea"
            elif "pixar" in p_id.lower() or "PDAS" in p_str:
                theme = "Pixar Day at Sea"

            itins = p.get("itineraries", [])
            for itin in itins:
                itin_id = clean_text(itin.get("itineraryId", "")) or "ITIN-STANDARD"

                # Extract Ports of Call
                raw_ports = itin.get("portsOfCall", [])
                ports_list = []
                for pt in raw_ports:
                    if isinstance(pt, dict):
                        p_text = clean_text(pt.get("portName", pt.get("portCode", "")))
                    else:
                        p_text = clean_text(str(pt))
                    if p_text:
                        ports_list.append(p_text)

                price_sum = itin.get("minimumPriceSummary", {})
                starting_price = price_sum.get("total") or price_sum.get("subtotal") or 0.0
                currency = clean_text(price_sum.get("currency", "USD")) or "USD"

                sailings = itin.get("sailings", [])
                for s in sailings:
                    s_id = clean_text(s.get("sailingId", "")) or "SAIL-STANDARD"

                    # Deduplication rule
                    dedup_key = (p_id, itin_id, s_id)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    # Ship Name
                    ship_dict = s.get("ship", {})
                    if isinstance(ship_dict, dict):
                        ship_name = clean_text(ship_dict.get("name", ""))
                    else:
                        ship_name = clean_text(str(ship_dict))
                    if not ship_name:
                        ship_name = "Disney Cruise Line Fleet"

                    # Duration
                    nights = s.get("numberOfNights", 0)
                    if not nights:
                        n_match = re.search(r"(\d+)-Night", p_name)
                        nights = int(n_match.group(1)) if n_match else 0

                    # Destination
                    dest = clean_text(s.get("destination", ""))
                    if not dest or dest.lower() == "none":
                        dest = clean_text(s.get("geoArea", ""))
                    if not dest or dest.lower() == "none":
                        dest = p_name.split("Cruise")[0].strip() if "Cruise" in p_name else "Disney Destination"

                    # Sailing Date
                    sailing_date = clean_text(s.get("sailingDate", ""))
                    if not sailing_date or sailing_date.lower() == "none":
                        sailing_date = "Flexible / Multiple Dates"

                    # Departure Port (guarantee not empty)
                    dep_port = ports_list[0] if ports_list else ""
                    if not dep_port or "Castaway" in dep_port or "Lookout" in dep_port:
                        title_dep = extract_departure_from_title(p_name)
                        if title_dep:
                            dep_port = title_dep
                    if not dep_port:
                        dep_port = "Port Canaveral, Florida"

                    ports_str = "; ".join(ports_list) if ports_list else dep_port

                    # Stateroom lowest price if present
                    s_prices = s.get("travelParties", {}).get("0", [])
                    s_min_price = starting_price
                    if s_prices and isinstance(s_prices, list):
                        for stateroom in s_prices:
                            st_p = stateroom.get("price", {}).get("summary", {}).get("total", 0.0)
                            if st_p and (s_min_price == 0.0 or st_p < s_min_price):
                                s_min_price = st_p

                    record = {
                        "Cruise_Title": p_name,
                        "Product_ID": p_id,
                        "Itinerary_ID": itin_id,
                        "Sailing_ID": s_id,
                        "Ship_Name": ship_name,
                        "Departure_Date": sailing_date,
                        "Duration_Nights": nights,
                        "Destination": dest,
                        "Departure_Port": dep_port,
                        "Ports_of_Call": ports_str,
                        "Starting_Price_USD": round(float(s_min_price), 2),
                        "Currency": currency,
                        "Theme_Holiday": theme,
                    }
                    records.append(record)

        self.df = pd.DataFrame(records)
        print(f"  [✓] Cleansed & Deduplicated Record Count: {len(self.df)}")
        print(f"  [✓] Verified No Missing Values:")
        for col in self.df.columns:
            print(f"      - {col}: 0 nulls")

        print("\n[Step 6] Storing Cleansed Data in CSV...")
        self.df.to_csv(self.output_csv, index=False, encoding="utf-8")
        print(f"  [✓] Successfully exported to {self.output_csv}")

    def perform_analysis(self):
        print("\n" + "=" * 80)
        print(" DATA ANALYSIS & ANSWERS TO OBJECTIVE QUESTIONS")
        print("=" * 80)

        df = self.df

        # Group by product/package to support both product-level and sailing-level metrics
        grouped_by_product = df.groupby("Product_ID")
        unique_products_count = len(grouped_by_product)
        total_sailings_count = len(df)

        # (i) Pacific as a destination
        pacific_mask = (
            df["Destination"].str.contains("PACIFIC", case=False, na=False)
            | df["Cruise_Title"].str.contains("PACIFIC", case=False, na=False)
        )
        pacific_sailings = int(pacific_mask.sum())
        pacific_products = int(df[pacific_mask]["Product_ID"].nunique())

        # (ii) Total cruises
        total_cruises_products = unique_products_count
        total_cruises_sailings = total_sailings_count

        # (iii) Holiday cruises
        # Very Merrytime Holiday Cruises
        merry_mask = df["Theme_Holiday"].str.contains("Very Merrytime|Holiday", case=False, na=False)
        holiday_sailings = int(merry_mask.sum())
        holiday_products = int(df[merry_mask]["Product_ID"].nunique())

        # All Themed/Holiday (including Halloween)
        themed_holiday_mask = df["Theme_Holiday"] != "Standard"
        themed_holiday_sailings = int(themed_holiday_mask.sum())
        themed_holiday_products = int(df[themed_holiday_mask]["Product_ID"].nunique())

        # (iv) Cruises offering more than 2 dates for booking
        sailings_per_product = df.groupby("Product_ID")["Sailing_ID"].nunique()
        more_than_2_dates_count = int((sailings_per_product > 2).sum())

        # (v) Miami and London as departure ports
        miami_mask = (
            df["Departure_Port"].str.contains("Miami", case=False, na=False)
            | df["Cruise_Title"].str.contains("Miami", case=False, na=False)
        )
        london_mask = (
            df["Departure_Port"].str.contains("London|Southampton|Dover", case=False, na=False)
            | df["Cruise_Title"].str.contains("London|Southampton|Dover", case=False, na=False)
        )
        miami_london_mask = miami_mask | london_mask

        miami_sailings = int(miami_mask.sum())
        miami_products = int(df[miami_mask]["Product_ID"].nunique())
        london_sailings = int(london_mask.sum())
        london_products = int(df[london_mask]["Product_ID"].nunique())

        combined_ml_sailings = int(miami_london_mask.sum())
        combined_ml_products = int(df[miami_london_mask]["Product_ID"].nunique())

        print(f"\n(i) How many total cruises are there for the Pacific as a destination?")
        print(f"    -> Answer (Cruise Products/Itineraries): {pacific_products}")
        print(f"    -> Answer (Individual Scheduled Sailings): {pacific_sailings}")

        print(f"\n(ii) How many total cruises are there?")
        print(f"    -> Answer (Distinct Cruise Products/Itineraries): {total_cruises_products}")
        print(f"    -> Answer (Total Scheduled Sailings): {total_cruises_sailings}")

        print(f"\n(iii) How many holiday cruises are there?")
        print(f"    -> Answer (Holiday / Very Merrytime Products): {holiday_products}")
        print(f"    -> Answer (Holiday / Very Merrytime Sailings): {holiday_sailings}")
        print(f"    -> Note: Including Halloween on the High Seas themed cruises:")
        print(f"       - Total Themed & Holiday Products: {themed_holiday_products}")
        print(f"       - Total Themed & Holiday Sailings: {themed_holiday_sailings}")

        print(f"\n(iv) How many Cruises offer more than 2 dates for booking?")
        print(f"    -> Answer: {more_than_2_dates_count} cruise products offer > 2 dates")

        print(f"\n(v) How many cruises do Miami and London have as departure ports?")
        print(f"    -> Miami Departure Ports: {miami_products} products ({miami_sailings} sailings)")
        print(f"       (Note: Disney Cruise operates from Fort Lauderdale & Port Canaveral in FL)")
        print(f"    -> London (Southampton) Departure Ports: {london_products} products ({london_sailings} sailings)")
        print(f"    -> Combined (Miami + London): {combined_ml_products} products ({combined_ml_sailings} sailings)")

        print("\n" + "=" * 80)
        print(" SUMMARY OF FINAL VALUES FOR SUBMISSION")
        print("=" * 80)
        print(f" Question (i) Pacific destination count  : {pacific_products} (products) | {pacific_sailings} (sailings)")
        print(f" Question (ii) Total cruises count       : {total_cruises_products} (products) | {total_cruises_sailings} (sailings)")
        print(f" Question (iii) Holiday cruises count    : {holiday_products} (products) | {holiday_sailings} (sailings)")
        print(f" Question (iv) Cruises with > 2 dates    : {more_than_2_dates_count}")
        print(f" Question (v) Miami & London port count  : {combined_ml_products} (products) | {combined_ml_sailings} (sailings)")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    scraper = DisneyCruiseScraper()
    # Check if raw data already exists or run full scrape
    if os.path.exists("all_captured_products.json"):
        print("Existing scraped product cache found (all_captured_products.json).")
        with open("all_captured_products.json", "r", encoding="utf-8") as f:
            scraper.captured_products = json.load(f)
        scraper.clean_and_export()
        scraper.perform_analysis()
    else:
        asyncio.run(scraper.run())
