import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone

def get_zaptec_token(username, password):
    url = "https://api.zaptec.com/oauth/token"
    payload = {
        "grant_type": "password",
        "username": username,
        "password": password
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(url, data=payload, headers=headers)
    response.raise_for_status()
    return response.json().get("access_token")

def fetch_zaptec_sessions(token):
    url = "https://api.zaptec.com/api/chargehistory"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    
    all_raw_sessions = []
    page = 1
    total_pages = 1
    
    # Loopa igenom alla sidor för att få med samtliga sessioner
    while page <= total_pages:
        params = {"PageIndex": page} if page > 1 else {}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict):
            total_pages = data.get("Pages", 1)
            page_data = data.get("Data", [])
            if isinstance(page_data, list):
                all_raw_sessions.extend(page_data)
        elif isinstance(data, list):
            all_raw_sessions.extend(data)
            break
            
        page += 1
        if page > total_pages:
            break

    formatted_sessions = []
    for s in all_raw_sessions:
        if not isinstance(s, dict):
            continue
            
        start_dt = s.get("startDateTime") or s.get("StartDateTime")
        energy = s.get("energy") or s.get("Energy", 0.0)
        user_name = s.get("userFullName") or s.get("UserFullName") or "Övriga bilar"
        
        date_str = ""
        if start_dt:
            try:
                dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = str(start_dt)[:16].replace("T", " ")

        formatted_sessions.append({
            "date": date_str,
            "car": user_name,
            "kwh": float(energy),
            "cost": 0.0
        })
        
    return formatted_sessions

def process_driving_data(excel_path="audi_trips.xlsx"):
    if not os.path.exists(excel_path):
        print(f"Varning: {excel_path} hittades inte. Genererar tom kördata.")
        return {}
    
    df = pd.read_excel(excel_path)
    
    date_col = next((c for c in df.columns if 'dat' in c.lower() or 'date' in c.lower()), df.columns[0])
    dist_col = next((c for c in df.columns if 'dist' in c.lower() or 'km' in c.lower() or 'mil' in c.lower()), df.columns[1])
    
    df['parsed_date'] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['parsed_date'])
    df['ym'] = df['parsed_date'].dt.strftime('%Y-%m')
    
    def clean_distance(val):
        if pd.isna(val):
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = str(val).lower().replace('km', '').replace(' ', '').replace(',', '.')
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    df['km_num'] = df[dist_col].apply(clean_distance)
    
    grouped = df.groupby('ym')['km_num'].sum().to_dict()
    driving_data = {}
    for ym, km in grouped.items():
        driving_data[ym] = {"distance_km": float(km)}
        
    return driving_data

def main():
    username = os.environ.get("ZAPTEC_USERNAME")
    password = os.environ.get("ZAPTEC_PASSWORD")
    
    sessions = []
    if username and password:
        try:
            print("Ansluter till Zaptec API...")
            token = get_zaptec_token(username, password)
            sessions = fetch_zaptec_sessions(token)
            print(f"Hämtade totalt {len(sessions)} laddsessioner från alla sidor hos Zaptec.")
        except Exception as e:
            print(f"Kunde inte hämta Zaptec-data: {e}")
    else:
        print("OBS: ZAPTEC_USERNAME eller ZAPTEC_PASSWORD saknas i miljövariablerna.")

    print("Bearbetar kördata från audi_trips.xlsx...")
    driving = process_driving_data("audi_trips.xlsx")
    
    output = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions,
        "driving": driving
    }
    
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("docs/data.json har skapats framgångsrikt!")

if __name__ == "__main__":
    main()
