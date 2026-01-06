import os
import requests
from dotenv import load_dotenv, find_dotenv

# 1. Load & Sanitize Key
load_dotenv(find_dotenv())
raw_key = os.getenv("GOOGLE_API_KEY")

if not raw_key:
    print("❌ ERROR: Key missing from .env file.")
    exit()

# Force remove any accidental spaces or newlines
GOOGLE_API_KEY = raw_key.strip()
print(f"🔑 Key Loaded: {GOOGLE_API_KEY[:5]}... (Cleaned)")

def test_geocoding():
    print("\n--- TEST 1: GEOCODING API (New York) ---")
    # Using 'New York' which never fails
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address=New+York&key={GOOGLE_API_KEY}"
    
    resp = requests.get(url).json()
    
    if resp.get('status') == 'OK':
        print("✅ SUCCESS! Coordinates found.")
        loc = resp['results'][0]['geometry']['location']
        print(f"   Lat: {loc['lat']}, Lng: {loc['lng']}")
        return True
    else:
        print(f"❌ FAILED. Status: {resp.get('status')}")
        print(f"   Full Response: {resp}")
        return False

def test_places():
    print("\n--- TEST 2: PLACES API (Search 'Cafe') ---")
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress"
    }
    payload = {"textQuery": "Cafe in New York"}
    
    resp = requests.post(url, headers=headers, json=payload)
    
    if resp.status_code == 200:
        data = resp.json()
        if 'places' in data:
            print(f"✅ SUCCESS! Found {len(data['places'])} businesses.")
            print(f"   Example: {data['places'][0]['displayName']['text']}")
            return True
    
    print(f"❌ FAILED. Code: {resp.status_code}")
    print(f"   Response: {resp.text}")
    return False

if __name__ == "__main__":
    geo_ok = test_geocoding()
    places_ok = test_places()
    
    if geo_ok and places_ok:
        print("\n🎉 ALL SYSTEMS GO! You are ready to run the main app.")
    else:
        print("\n⚠️ SYSTEM CHECK FAILED. See errors above.")