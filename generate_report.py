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
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    print(data)
    
    # Hitta listan oavsett om den ligger direkt eller under en nyckel
    sessions_list = []
    if isinstance(data, list):
        sessions_list = data
    elif isinstance(data, dict):
        for key in ["Data", "Pages", "Items", "Entries", "Result", "Detail"]:
            if key in data and isinstance(data[key], list):
                sessions_list = data[key]
                break
        if not sessions_list:
            # Om inga kända nycklar matchar, leta efter första listan i diktet
            for v in data.values():
                if isinstance(v, list):
                    sessions_list = v
                    break

    formatted_sessions = []
    for s in sessions_list:
        if not isinstance(s, dict):
            continue
            
        # Sök igenom möjliga fältnamn för datum, energi och användare
        start_dt = (
            s.get("startDateTime") or 
            s.get("StartDateTime") or 
            s.get("StartTime") or 
            s.get("startTime") or
            s.get("Date") or
            s.get("date")
        )
        
        energy = (
            s.get("energy") or 
            s.get("Energy") or 
            s.get("KWh") or 
            s.get("kWh") or 
            s.get("TotalEnergy") or 
            0.0
        )
        
        user_name = (
            s.get("userFullName") or 
            s.get("UserFullName") or 
            s.get("UserName") or 
            s.get("userName") or 
            s.get("User") or 
            "Övriga bilar"
        )
        
        date_str = ""
        if start_dt:
            try:
                dt = datetime.fromisoformat(str(start_dt).replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = str(start_dt)[:16].replace("T", " ")

        # Om energivärdet är i Wh (> 1000 och inget decimaltal), konvertera till kWh
        try:
            energy_val = float(energy)
            if energy_val > 1000:
                energy_val = energy_val / 1000.0
        except (ValueError, TypeError):
            energy_val = 0.0

        formatted_sessions.append({
            "date": date_str,
            "car": str(user_name),
            "kwh": energy_val,
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
            print(f"Hämtade och bearbetade {len(sessions)} laddsessioner från Zaptec.")
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
    
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("data.json har skapats framgångsrikt!")

if __name__ == "__main__":
    main()
