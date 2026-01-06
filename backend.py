import os
import json
import requests
from google import genai
from groq import Groq
from dotenv import load_dotenv, find_dotenv # Added find_dotenv for safety
import PIL.Image

# 1. Load Environment Variables & Sanitize
load_dotenv(find_dotenv())

# Helper to get clean keys
def get_key(name):
    val = os.getenv(name)
    return val.strip() if val else None

GOOGLE_API_KEY = get_key("GOOGLE_API_KEY")
GROQ_API_KEY = get_key("GROQ_API_KEY")
AI_STUDIO_KEY = get_key("AI_STUDIO_KEY")

# 2. Initialize AI Clients
client = genai.Client(api_key=AI_STUDIO_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

# --- CORE FUNCTIONS ---

def get_bbox_from_pincode(pincode):
    """
    Retrieves the strict 'viewport' (official boundary) for a pincode.
    """
    print(f"Fetching boundary for Pincode: {pincode}...")
    
    # FIX 1: Use proper params dictionary (handles spaces/encoding automatically)
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": pincode,
        "key": GOOGLE_API_KEY
    }
    
    try:
        resp = requests.get(url, params=params).json()
        
        # Check for specific failure modes
        if resp['status'] == 'ZERO_RESULTS':
            print(f"Warning: Google found no location for '{pincode}'. Trying adding country...")
            # Retry mechanism: Append "USA" if it failed
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
            print(f"Geocoding Error: {resp['status']}")
            if 'error_message' in resp:
                print(f"   Reason: {resp['error_message']}")
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_bbox_from_image(image_path):
    """
    Uses Gemini 1.5 Flash to estimate coordinates from a map screenshot.
    """
    print(f"📸 Analyzing Map Image: {image_path}...")
    
    try:
        img = PIL.Image.open(image_path)
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
        print(f"Vision Error: {e}")
        return None

def search_places_strict(query, bbox):
    """
    Searches Google Places within the strict bbox.
    """
    print(f"Searching for '{query}' inside strict boundary...")
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.editorialSummary,places.types,places.websiteUri"
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
    return resp.json().get('places', [])

def verify_lead_agent(place, user_criteria):
    """
    Uses Llama 3.3 (Groq) to audit the lead.
    """
    name = place.get('displayName', {}).get('text', 'Unknown')
    summary = place.get('editorialSummary', {}).get('text', 'No summary provided')
    types = place.get('types', [])
    
    prompt = f"""
    Role: Strict Data Auditor.
    User Criteria: "{user_criteria}"
    
    Candidate:
    - Name: {name}
    - Types: {types}
    - Summary: {summary}
    
    Task: Return JSON only. {{"status": "APPROVED" | "REJECTED", "reason": "Short explanation"}}
    """
    
    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )
    
    return json.loads(completion.choices[0].message.content)

# --- TEST BLOCK ---
if __name__ == "__main__":
    # Test 1: Let's use a full address to be safe, though the code now handles raw zip better
    test_pincode = "90210" 
    test_query = "Coffee Shop"
    test_criteria = "Must be an independent cafe. NO big chains like Starbucks or Peets."

    # 1. Get Boundary
    bbox = get_bbox_from_pincode(test_pincode)
    
    if bbox:
        print(f"Boundary Found: {bbox}")
        
        # 2. Search Data
        leads = search_places_strict(test_query, bbox)
        print(f"Found {len(leads)} raw leads.")
        
        # 3. Verify
        if leads:
            print("🤖 Agent Verification Started (Checking first 3)...")
            for lead in leads[:3]:
                verdict = verify_lead_agent(lead, test_criteria)
                print(f"{lead['displayName']['text']}: {verdict['status']} ({verdict['reason']})")
        else:
            print("No leads found.")
    else:
        print("Could not fetch boundary.")