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

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(
    page_title="ZoneScout | AI Lead Gen",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load Environment Variables & Sanitize
load_dotenv(find_dotenv())

def get_key(name):
    """Helper to safely get and clean API keys."""
    val = os.getenv(name)
    return val.strip() if val else None

GOOGLE_API_KEY = get_key("GOOGLE_API_KEY")
GROQ_API_KEY = get_key("GROQ_API_KEY")
AI_STUDIO_KEY = get_key("AI_STUDIO_KEY")

# Initialize AI Clients
try:
    client = genai.Client(api_key=AI_STUDIO_KEY)
    groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    st.error(f"❌ API Setup Error: {e}")
    st.stop()

# --- 2. BACKEND LOGIC ---

@st.cache_data(show_spinner=False)
def get_bbox_from_pincode(pincode):
    """Fetches strict viewport for a pincode using Geocoding API."""
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
    """Uses Gemini 1.5 Flash to 'read' the map screenshot."""
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
    """Fetches places strictly within the bounding box."""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.editorialSummary,places.types,places.websiteUri,places.rating,places.nationalPhoneNumber,places.googleMapsUri"
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

async def verify_single_lead(place, criteria):
    """Async function to verify one lead using Groq (Llama 3.3)."""
    name = place.get('displayName', {}).get('text', 'Unknown')
    summary = place.get('editorialSummary', {}).get('text', 'No summary provided')
    types = place.get('types', [])
    
    prompt = f"""
    Role: Strict Business Auditor.
    User Criteria: "{criteria}"
    
    Candidate:
    - Name: {name}
    - Types: {types}
    - Summary: {summary}
    
    Task: Does this STRICTLY match the criteria?
    Return JSON only: {{"status": "APPROVED" | "REJECTED", "reason": "Short explanation"}}
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
        place['ai_status'] = result['status']
        place['ai_reason'] = result['reason']
        return place
    except:
        place['ai_status'] = "ERROR"
        place['ai_reason'] = "AI Timeout"
        return place

async def verify_all_leads_async(leads, criteria):
    """Runs verification for all leads in parallel."""
    tasks = [verify_single_lead(lead, criteria) for lead in leads]
    return await asyncio.gather(*tasks)

# --- NEW: HELPER FOR DYNAMIC SOCIAL LINKS ---
def get_social_link(name, types):
    """Decides if the business needs Instagram or LinkedIn."""
    # List of B2C categories that perform better on Instagram
    insta_categories = [
        'cafe', 'restaurant', 'bakery', 'bar', 'night_club', 
        'clothing_store', 'beauty_salon', 'spa', 'gym', 
        'florist', 'meal_delivery', 'meal_takeaway', 'store', 
        'shopping_mall', 'tourist_attraction'
    ]
    
    # Check if any business type matches our Insta list
    is_insta = any(t in insta_categories for t in types)
    
    if is_insta:
        return "Instagram", f"https://www.instagram.com/explore/tags/{name.replace(' ', '').lower()}/"
    else:
        # Default to LinkedIn for B2B / Professional / Other
        return "LinkedIn", f"https://www.linkedin.com/search/results/all/?keywords={name.replace(' ', '%20')}"

# --- 3. STREAMLIT UI ---

# Sidebar
with st.sidebar:
    st.title("ZoneScout 📍")
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
                    st.error("Invalid Pincode or API Error")
                    
    elif input_mode == "Map Screenshot":
        uploaded_file = st.file_uploader("Upload Map", type=['png', 'jpg'])
        if uploaded_file and st.button("Analyze Map"):
            st.image(uploaded_file, caption="Target Area", use_container_width=True)
            with st.spinner("Gemini Vision is analyzing boundaries..."):
                bbox = get_bbox_from_image(uploaded_file)
                if bbox:
                    st.success("Coordinates Extracted!")
                    st.json(bbox)
                    st.session_state['bbox'] = bbox

    st.markdown("---")
    st.subheader("2. Search Parameters")
    query = st.text_input("Find Businesses:", "Coffee Shop") 
    criteria = st.text_area("Strict AI Criteria:", "Must be a small business. NO big chains like Starbucks.")

# Main Screen
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
                    status.update(label="No leads found in this zone.", state="error")
                    st.stop()
                
                status.write(f"Found {len(raw_leads)} raw candidates. Deploying AI Agents...")
                verified_leads = asyncio.run(verify_all_leads_async(raw_leads, criteria))
                status.update(label="Audit Complete!", state="complete")
            
            approved = [l for l in verified_leads if l.get('ai_status') == 'APPROVED']
            rejected = [l for l in verified_leads if l.get('ai_status') == 'REJECTED']
            
            col1, col2 = st.columns(2)
            col1.metric("Qualified Leads", len(approved))
            col2.metric("Rejected (Noise)", len(rejected))

            # --- DISPLAY RESULTS ---
            st.subheader("✅ Verified Leads")
            for lead in approved:
                name = lead['displayName']['text']
                phone = lead.get('nationalPhoneNumber', 'Not listed')
                website = lead.get('websiteUri', '#')
                maps_link = lead.get('googleMapsUri', '#')
                types = lead.get('types', [])
                
                # Dynamic Social Link
                social_platform, social_url = get_social_link(name, types)
                social_icon = "📸" if social_platform == "Instagram" else "👔"

                with st.expander(f"{name} (⭐ {lead.get('rating', 'N/A')})"):
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        st.markdown(f"**📍 Address:** {lead.get('formattedAddress')}")
                        st.markdown(f"**📞 Phone:** `{phone}`")
                        st.markdown(f"**🤖 AI Analysis:** {lead['ai_reason']}")
                    with c2:
                        st.markdown("### Quick Links")
                        if website != '#':
                            st.markdown(f"[🌐 Visit Website]({website})")
                        if maps_link != '#':
                            st.markdown(f"[🗺️ Open in Maps]({maps_link})")
                        st.markdown(f"[{social_icon} Search {social_platform}]({social_url})")
            
            if rejected:
                with st.expander("Show Rejected Leads (Hidden by default)"):
                    for lead in rejected:
                        st.markdown(f"**{lead['displayName']['text']}**: ❌ {lead['ai_reason']}")

else:
    st.info("👈 Please define your Search Zone in the sidebar to begin.")