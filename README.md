# Zone-Scout

# ZoneScout 📍

**ZoneScout is an AI-powered business intelligence tool that finds, filters, and verifies local leads.**

Unlike standard maps which just list businesses, ZoneScout uses a **Multi-Agent AI** approach. It scans a specific geographic zone (via Zip Code or Map Screenshot), extracts business data, and then uses a **Reasoning Agent (Llama 3.3)** to audit every single lead against your strict criteria. It automatically generates social media links (LinkedIn for tech, Instagram for retail) and provides verified contact details.

---

## 🛠️ Tech Stack

* **Frontend:** Streamlit (Python)
* **Geospatial:** Google Maps Geocoding & Places API (v1)
* **Vision AI:** Google Gemini 1.5 Flash (for analyzing map images)
* **Reasoning AI:** Groq API running Llama 3.3 70B (for auditing leads)
* **Environment:** Python 3.10+, Dotenv for security

---

## ⚙️ How It Works (System Flow)

![ZoneScout Architecture] (Flow Diagram.png)


# 🚀 How to Run

## Clone the Repository

    git clone <repository_url>
    cd ZoneScout

## Install Dependencies

    pip install -r requirements.txt

## Set Up API Keys

Create a file named `.env` in the root folder and add your API keys:

    GOOGLE_API_KEY="your_google_maps_key"
    GROQ_API_KEY="your_groq_key"
    AI_STUDIO_KEY="your_gemini_key"

## Run the App

    streamlit run app.py

---

## 👨‍💻 Built By

**Sravanakumar Sathish**
🔗 [LinkedIn](https://www.linkedin.com/in/sravanakumar-sathish/)

