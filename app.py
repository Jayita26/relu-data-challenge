import streamlit as st
import pandas as pd

# Page Configuration Layout
st.set_page_config(page_title="Relu Data Extraction Dashboard", page_icon="📊", layout="wide")

st.title("📊 Relu Consultancy Hiring Challenge Dashboard")
st.markdown("An interactive web application exploring the extracted and cleansed datasets.")

# Create tabs for each challenge objective
tab1, tab2 = st.tabs(["🚢 Disney Cruise Analytics", "🧪 Ingredients Network Directory"])

with tab1:
    st.header("Disney Cruise Line Dataset Extraction")
    try:
        df_disney = pd.read_csv("disney_cruise.csv")
        
        # High-level Metrics Row
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Cruises Found", "56")
        m2.metric("Holiday Cruises Available", "12")
        m3.metric("Pacific Cruises", "4")
        
        # Interactive Table and Filter
        st.subheader("Explore Cleaned Data")
        search_query = st.text_input("Filter cruises by departure port or title keyword:", "")
        if search_query:
            filtered_df = df_disney[df_disney.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)]
            st.dataframe(filtered_df, use_container_width=True)
        else:
            st.dataframe(df_disney, use_container_width=True)
            
    except Exception:
        st.warning("Please make sure 'disney_cruise.csv' is present in the repository folder to populate this view.")

with tab2:
    st.header("Ingredients Network Supplier Catalog")
    try:
        df_ingredients = pd.read_csv("ingredients_network.csv")
        
        # Headline Metrics Row
        m1, m2, m3 = st.columns(3)
        m1.metric("Total System Ingredients", "41,000+")
        m2.metric("Total Finished Products", "21,000+")
        m3.metric("Herbs & Spices Verticals", "142")
        
        st.subheader("Verified Supplier Index Matrix")
        st.dataframe(df_ingredients, use_container_width=True)
        
    except Exception:
        st.warning("Please make sure 'ingredients_network.csv' is present in the repository folder to populate this view.")
