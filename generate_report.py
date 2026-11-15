import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

def get_zaptec_token(username, password):
    url = "https://api.zaptec.com/oauth/token"
    payload = {
        "grant_type": "password",
        "username": username,
        "password": password
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    print("Ansluter till Zaptec API för att hämta token...")
    response = requests.post(url, data=payload, headers=headers)
    response.raise_for_status()
    print("Token hämtad framgångsrikt.")
    return response.json().get("access_token")

spot_price_cache = {}

def get_spot_prices(date_str):
    print(f"  [ELPRIS-STEG 1] Kontrollerar cache för datum: {date_str}...")
    if date_str in spot_price_cache:
        print(f"  [ELPRIS-STEG 1b] Pris för {date_str} hittades direkt i cache.")
        return spot_price_cache[date_str]
    
    print(f"  [ELPRIS-STEG 2] Cache saknade {date_str}. Förbereder API-anrop till elprisetjustnu.se (SE3)...")
    try:
        parts = date_str.split("-")
        year, month, day = parts[0], parts[1], parts[2]
        url = f"https://www.elprisetjustnu.se/api/v1/prices/{year}/{month}-{day}_SE3.json"
        print(f"  [ELPRIS-STEG 3] Skickar HTTP GET till: {url}")
        
        resp = requests.get(url, timeout=5)
        print(f"  [ELPRIS-STEG 4] Mottog svar. Statuskod: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            spot_price_cache[date_str] = data
            print(f"  [ELPRIS-STEG 5] Parsade JSON: Sparade {len(data)} timpriser i cache för {date_str}.")
            return data
        else:
            print(f"  [ELPRIS-STEG 5-FEL] API svarade med status {resp.status_code} för {date_str}.")
    except Exception as e:
        print(f"  [ELPRIS-STEG 5-EXCEPTION] Ett fel uppstod vid hämtning av elpriser för {date_str}: {e}")
    
    print(f"  [ELPRIS-STEG 5-FALLBACK] Returnerar tom lista för {date_str}.")
    return []

def calculate_cost(start_str, end_str, energy_kwh):
    if energy_kwh <= 0:
        return 0.0
    try:
        if start_str:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else start_dt + timedelta(hours=2)
            date_str = start_dt.strftime("%Y-%m-%d")
            
            prices = get_spot_prices(date_str)
            if prices:
                session_prices = []
                current = start_dt
                while current < end_dt:
                    hour = current.hour
                    matching_price = next((p for p in prices if datetime.fromisoformat(p["time_start"].replace("Z", "+00:00")).hour == hour), None)
                    if matching_price:
                        session_prices.append(matching_price.get("SEK_per_kWh", 0.0))
                    current += timedelta(hours=1)
                
                if session_prices:
                    avg_price = sum(session_prices) / len(session_prices)
                    cost = round(energy_kwh * avg_price, 2)
                    print(f"  [KOSTNAD] Beräknad kostnad för {date_str} ({energy_kwh} kWh á {avg_price:.2f} kr/kWh): {cost} kr")
                    return cost
    except Exception as e:
        print(f"  [KOSTNAD-FEL] Kunde inte beräkna spotpriskostnad: {e}")
    
    fallback_cost = round(energy_kwh * 1.50, 2)
    print(f"  [KOSTNAD-FALLBACK] Använder standardpris (1.50 kr/kWh) -> {fallback_cost} kr")
    return fallback_cost

def fetch_zaptec_sessions(token):
    url = "https://api.zaptec.com/api/chargehistory"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    
    all_raw_sessions = []
    page = 1
    total_pages = 1
    
    print("Hämtar laddningssessioner från Zaptec API (med paginering)...")
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
            
        print(f"Hämtade sida {page} av {total_pages} (Totalt hittills: {len(all_raw_sessions)} sessioner).")
        page += 1
        if page > total_pages:
            break

    formatted_sessions = []
    for s in all_raw_sessions:
        if not isinstance(s, dict):
            continue
            
        start_dt = s.get("startDateTime") or s.get("StartDateTime")
        end_dt = s.get("endDateTime") or s.get("EndDateTime")
        energy = s.get("energy") or s.get("Energy", 0.0)
        user_name = (
            s.get("userFullName") or 
            s.get("UserFullName") or 
            s.get("UserName") or 
            s.get("userName") or 
            "Övriga bilar"
        )
        
        date_str = ""
        if start_dt:
            try:
                dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = str(start_dt)[:16].replace("T", " ")

        formatted_sessions.append({
            "raw_start": start_dt,
            "date": date_str,
            "car": str(user_name),
            "kwh": float(energy),
            "end_dt": end_dt,
            "start_dt_obj": start_dt
        })

    # Sortera sessioner kronologiskt för att hitta den första laddningen
    valid_sessions = [s for s in formatted_sessions if s["raw_start"]]
    if valid_sessions:
        valid_sessions.sort(key=lambda x: x["raw_start"])
        first_session_date = valid_sessions[0]["raw_start"][:10]
        print(f"👉 Första registrerade laddsessionen ägde rum den: {first_session_date}")
        
        # Filtrera bort eventuella sessioner som ligger före första riktiga datumet om önskvärt,
        # eller säkerställ att vi bara bearbetar elpriser från och med den första laddningen.
        filtered_formatted = []
        for s in formatted_sessions:
            if s["raw_start"] and s["raw_start"][:10] >= first_session_date:
                # Beräkna kostnad med loggning
                print(f"\nBearbetar session datum {s['date']} ({s['kwh']} kWh):")
                cost = calculate_cost(s["start_dt_obj"], s["end_dt"], s["kwh"])
                filtered_formatted.append({
                    "date": s["date"],
                    "car": s["car"],
                    "kwh": s["kwh"],
                    "cost": cost
                })
        return filtered_formatted

    return []

def process_driving_data(excel_path="audi_trips.xlsx"):
    if not os.path.exists(excel_path):
        print(f"Varning: {excel_path} hittades inte. Genererar tom kördata.")
        return {}
    
    print(f"Bearbetar kördata från {excel_path}...")
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
            token = get_zaptec_token(username, password)
            sessions = fetch_zaptec_sessions(token)
            print(f"\nTotalt bearbetade {len(sessions)} laddsessioner.")
        except Exception as e:
            print(f"Kunde inte hämta Zaptec-data: {e}")
    else:
        print("OBS: ZAPTEC_USERNAME eller ZAPTEC_PASSWORD saknas i miljövariablerna.")

    driving = process_driving_data("audi_trips.xlsx")
    
    output = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions,
        "driving": driving
    }
    
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print("docs/data.json har skapats framgångsrikt med optimerad elprishämtning och fullständig loggning!")

if __name__ == "__main__":
    main()
