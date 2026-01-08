import streamlit as st
import os
import json
import requests
import asyncio
import pandas as pd
from google import genai
from groq import Groq
from dotenv import load_dotenv, find_dotenv
import PIL.Image
from bs4 import BeautifulSoup  

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="ZoneScout | AI Lead Gen",
    page_icon="compass tabicon.png", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load Environment Variables
load_dotenv(find_dotenv())

def get_key(name):
    val = os.getenv(name)
    return val.strip() if val else None

GOOGLE_API_KEY = get_key("GOOGLE_API_KEY")
GROQ_API_KEY = get_key("GROQ_API_KEY")
AI_STUDIO_KEY = get_key("AI_STUDIO_KEY")

try:
    client = genai.Client(api_key=AI_STUDIO_KEY)
    groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    st.error(f"❌ API Setup Error: {e}")
    st.stop()

# --- 2. BACKEND LOGIC ---

@st.cache_data(show_spinner=False)
def get_bbox_from_pincode(pincode):
    """Fetches strict viewport for a pincode."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": pincode, "key": GOOGLE_API_KEY}
    
    try:
        resp = requests.get(url, params=params).json()
        if resp['status'] == 'ZERO_RESULTS':
            params['address'] = f"{pincode}, USA"
            resp = requests.get(url, params=params).json()

        if resp['status'] == 'OK':
            viewport = resp['results'][0]['geometry']['viewport']
            return {
                'north': viewport['northeast']['lat'],
                'south': viewport['southwest']['lat'],
                'east': viewport['northeast']['lng'],
                'west': viewport['southwest']['lng']
            }
        else:
            return None
    except:
        return None

def get_bbox_from_image(image_file):
    """Uses Gemini to read map screenshots."""
    try:
        img = PIL.Image.open(image_file)
        prompt = """
        Analyze this map image.
        1. Identify the geographic area based on visible street names/landmarks.
        2. Estimate the precise Bounding Box (North, South, East, West coordinates).
        3. Return ONLY a JSON object: {"north": float, "south": float, "east": float, "west": float}.
        """
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[prompt, img]
        )
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"Vision AI Error: {e}")
        return None

def search_places_strict(query, bbox):
    """Fetches places including REVIEWS and WEBSITE URI."""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        # UPDATED: Added 'places.reviews' to the mask
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.editorialSummary,places.types,places.websiteUri,places.rating,places.nationalPhoneNumber,places.googleMapsUri,places.reviews"
    }
    payload = {
        "textQuery": query,
        "locationRestriction": {
            "rectangle": {
                "low": {"latitude": bbox['south'], "longitude": bbox['west']},
                "high": {"latitude": bbox['north'], "longitude": bbox['east']}
            }
        }
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        st.error(f"❌ Google API Error: {resp.status_code}")
        st.json(resp.json()) 
        return []
    
    return resp.json().get('places', [])

def scrape_website_text(url):
    """(New Agent) Visits the website and extracts main text."""
    if not url: return "No website provided."
    try:
        # Timeout set to 3 seconds to keep things fast
        response = requests.get(url, timeout=3, headers={"User-Agent": "ZoneScout-AI-Agent"})
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Kill script and style elements
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text()
            # Clean whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            return text[:1000] # Return first 1000 chars to save tokens
        return "Website reachable but content hidden."
    except:
        return "Website scrape failed (Connection Error)."

async def verify_single_lead(place, criteria):
    """(Updated Agent) Includes Review Analysis and Website Scraping."""
    name = place.get('displayName', {}).get('text', 'Unknown')
    summary = place.get('editorialSummary', {}).get('text', 'No summary provided')
    types = place.get('types', [])
    website_url = place.get('websiteUri', '')
    
    # 1. Fetch Reviews
    reviews_data = place.get('reviews', [])
    reviews_text = "\n".join([f"- {r.get('text', {}).get('text', '')}" for r in reviews_data[:3]]) # Top 3 reviews
    
    # 2. Scrape Website (Blocking call inside async - acceptable for small batch)
    scraped_content = "Skipped (No URL)"
    if website_url:
        scraped_content = scrape_website_text(website_url)

    # 3. The Super-Prompt
    prompt = f"""
    Role: Elite Business Intelligence Auditor.
    
    User Criteria: "{criteria}"
    
    Candidate Data:
    - Name: {name}
    - Types: {types}
    - Google Summary: {summary}
    - Website Homepage Content: "{scraped_content}"
    - Customer Reviews: 
    {reviews_text}
    
    Tasks:
    1. VERDICT: Does this match the criteria? (Status: APPROVED/REJECTED)
    2. ANALYSIS: Based on the reviews, what is GOOD and what is BAD about this place?
    
    Return JSON only: 
    {{
        "status": "APPROVED" | "REJECTED",
        "reason": "Why verified/rejected",
        "pros": ["Point 1", "Point 2"],
        "cons": ["Point 1", "Point 2"]
    }}
    """
    
    try:
        chat_completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        result = json.loads(chat_completion.choices[0].message.content)
        
        # Merge AI results back into the place object
        place['ai_status'] = result['status']
        place['ai_reason'] = result.get('reason', 'N/A')
        place['ai_pros'] = result.get('pros', [])
        place['ai_cons'] = result.get('cons', [])
        return place
    except:
        place['ai_status'] = "ERROR"
        place['ai_reason'] = "AI Timeout"
        place['ai_pros'] = []
        place['ai_cons'] = []
        return place

async def verify_all_leads_async(leads, criteria):
    tasks = [verify_single_lead(lead, criteria) for lead in leads]
    return await asyncio.gather(*tasks)

def get_social_link(name, types):
    insta_categories = ['cafe', 'restaurant', 'bakery', 'bar', 'clothing_store', 'beauty_salon', 'spa', 'gym']
    is_insta = any(t in insta_categories for t in types)
    if is_insta:
        return "Instagram", f"https://www.instagram.com/explore/tags/{name.replace(' ', '').lower()}/"
    else:
        return "LinkedIn", f"https://www.linkedin.com/search/results/all/?keywords={name.replace(' ', '%20')}"

# --- 3. STREAMLIT UI ---

with st.sidebar:
    # --- LOGO & BRANDING ---
    try:
        st.image("compass logo.png", use_container_width=True) 
    except:
        st.warning("⚠️ Add 'logo.png' to folder to see logo here.")
        
    st.title("ZoneScout")
    st.markdown("---")
    st.subheader("1. Define Zone")
    input_mode = st.radio("Input Method:", ["Pincode/Zip", "Map Screenshot"])
    
    if input_mode == "Pincode/Zip":
        pincode = st.text_input("Enter Code (e.g., 90210)")
        if st.button("Set Zone by Pincode"):
            with st.spinner("Fetching Geocodes..."):
                bbox = get_bbox_from_pincode(pincode)
                if bbox:
                    st.success(f"Locked: {pincode}")
                    st.session_state['bbox'] = bbox
                else:
                    st.error("Invalid Pincode")
                    
    elif input_mode == "Map Screenshot":
        uploaded_file = st.file_uploader("Upload Map", type=['png', 'jpg'])
        if uploaded_file and st.button("Analyze Map"):
            st.image(uploaded_file, caption="Target Area", use_container_width=True)
            with st.spinner("Gemini Vision is analyzing boundaries..."):
                bbox = get_bbox_from_image(uploaded_file)
                if bbox:
                    st.success("Coordinates Extracted!")
                    st.session_state['bbox'] = bbox

    st.markdown("---")
    st.subheader("2. Search Parameters")
    query = st.text_input("Find Businesses:", "Coffee Shop") 
    criteria = st.text_area("Strict AI Criteria:", "Must be a small business. NO big chains.")

st.header("Hyper-Local Business Intelligence")
st.markdown("Generate verified leads from specific map zones using Multimodal AI.")

if 'bbox' in st.session_state:
    bbox = st.session_state['bbox']
    center_lat = (bbox['north'] + bbox['south']) / 2
    center_lon = (bbox['east'] + bbox['west']) / 2
    st.map({"lat": [center_lat], "lon": [center_lon]}, zoom=13)
    
    if st.button("🚀 Scout Zone", type="primary"):
        if not query:
            st.warning("Please enter a search term.")
        else:
            with st.status("🕵️ Scouting Google Maps Database...", expanded=True) as status:
                raw_leads = search_places_strict(query, bbox)
                if not raw_leads:
                    status.update(label="No leads found.", state="error")
                    st.stop()
                
                status.write(f"Found {len(raw_leads)} raw candidates. Visiting websites & analyzing reviews...")
                verified_leads = asyncio.run(verify_all_leads_async(raw_leads, criteria))
                status.update(label="Audit Complete!", state="complete")
            
            approved = [l for l in verified_leads if l.get('ai_status') == 'APPROVED']
            rejected = [l for l in verified_leads if l.get('ai_status') == 'REJECTED']
            
            col1, col2 = st.columns(2)
            col1.metric("Qualified Leads", len(approved))
            col2.metric("Rejected (Noise)", len(rejected))

            st.subheader("✅ Verified Leads")
            for lead in approved:
                name = lead['displayName']['text']
                phone = lead.get('nationalPhoneNumber', 'Not listed')
                website = lead.get('websiteUri', '#')
                maps_link = lead.get('googleMapsUri', '#')
                types = lead.get('types', [])
                
                social_platform, social_url = get_social_link(name, types)
                social_icon = "📸" if social_platform == "Instagram" else "👔"

                with st.expander(f"{name} (⭐ {lead.get('rating', 'N/A')})"):
                    # Use 3 columns for better layout of new data
                    c1, c2, c3 = st.columns([1, 1, 1])
                    
                    with c1:
                        st.markdown(f"**📍 Details**")
                        st.markdown(f"{lead.get('formattedAddress')}")
                        st.markdown(f"`{phone}`")
                        if website != '#': st.markdown(f"[🌐 Website]({website})")
                        st.markdown(f"[{social_icon} {social_platform}]({social_url})")

                    with c2:
                        st.markdown("**🟢 The Good**")
                        for pro in lead.get('ai_pros', []):
                            st.markdown(f"- {pro}")
                            
                    with c3:
                        st.markdown("**🔴 The Bad**")
                        for con in lead.get('ai_cons', []):
                            st.markdown(f"- {con}")

                    st.info(f"**AI Reason:** {lead['ai_reason']}")
            
            if rejected:
                with st.expander("Show Rejected Leads"):
                    for lead in rejected:
                        st.markdown(f"**{lead['displayName']['text']}**: ❌ {lead['ai_reason']}")

else:
    st.info("👈 Please define your Search Zone in the sidebar to begin.")