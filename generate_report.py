import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
import pandas as pd

ZAPTEC_USERNAME = os.environ["ZAPTEC_USERNAME"]
ZAPTEC_PASSWORD = os.environ["ZAPTEC_PASSWORD"]
ELAREA = "SE3"
BASE_URL = "https://api.zaptec.com"

# Prisinställningar
VAT_MULTIPLIER = 1.25   # 25 % moms på spotpriset
GRID_AND_TAX_FEE = 0.50 # Påslag i kr/kWh (inkl. moms) för elöverföring, energiskatt och elhandelspåslag
FALLBACK_SPOT_PRICE = 1.50

# Enkel cache i minnet så varje datum bara hämtas en gång per körning
PRICE_CACHE = {}

def get_access_token() -> str:
    url = f"{BASE_URL}/oauth/token"
    payload = {"grant_type": "password", "username": ZAPTEC_USERNAME, "password": ZAPTEC_PASSWORD}
    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]

def fetch_spot_prices(date_str: str) -> list[dict]:
    if date_str in PRICE_CACHE:
        return PRICE_CACHE[date_str]

    year = date_str[:4]
    month_day = date_str[5:]
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{year}/{month_day}_{ELAREA}.json"
    
    try:
        resp = requests.get(url, timeout=10)
        print(f"Hämtar pris för {date_str}: Status {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            PRICE_CACHE[date_str] = data
            return data
    except Exception as e:
        print(f"Fel vid hämtning av elpris för {date_str}: {e}")

    PRICE_CACHE[date_str] = []
    return []

def calculate_session_cost(start_str: str, energy_kwh: float) -> float:
    try:
        # Tolka Zaptecs UTC-tid och konvertera till svensk lokal tid
        dt_utc = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZoneInfo("Europe/Stockholm"))
        
        date_str = dt_local.strftime("%Y-%m-%d")
        prices = fetch_spot_prices(date_str)
        
        spot_price = None
        for item in prices:
            t_start = datetime.fromisoformat(item["time_start"])
            t_end = datetime.fromisoformat(item["time_end"])
            if t_start <= dt_local < t_end:
                spot_price = float(item["SEK_per_kWh"])
                break
        
        if spot_price is None:
            spot_price = FALLBACK_SPOT_PRICE

        total_price_per_kwh = (spot_price * VAT_MULTIPLIER) + GRID_AND_TAX_FEE
        return energy_kwh * total_price_per_kwh
    except Exception:
        return energy_kwh * ((FALLBACK_SPOT_PRICE * VAT_MULTIPLIER) + GRID_AND_TAX_FEE)

def load_car_mapping() -> dict:
    if os.path.exists("car_mapping.json"):
        try:
            with open("car_mapping.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def process_driving_data() -> dict:
    driving_summary = {}
    excel_path = "audi_trips.xlsx"
    
    if os.path.exists(excel_path):
        try:
            df_raw = pd.read_excel(excel_path, sheet_name='Korttidsminne', header=None)
            header_row_idx = None
            for idx, row in df_raw.iterrows():
                row_str = str(row.values).lower()
                if 'körningens slut' in row_str or 'körd sträcka' in row_str:
                    header_row_idx = idx
                    break
            
            if header_row_idx is not None:
                df = pd.read_excel(excel_path, sheet_name='Korttidsminne', header=header_row_idx)
            else:
                df = pd.read_excel(excel_path, sheet_name='Korttidsminne', header=1)
                
            date_col = next((col for col in df.columns if 'slut' in str(col).lower() or 'datum' in str(col).lower() or 'date' in str(col).lower()), None)
            dist_col = next((col for col in df.columns if 'sträck' in str(col).lower() or 'distance' in str(col).lower() or 'km' in str(col).lower()), None)
            
            if date_col and dist_col:
                # LAGT TILL dayfirst=True HÄR:
                df['ParsedDate'] = pd.to_datetime(df[date_col], errors='coerce', dayfirst=True)
                df['Month'] = df['ParsedDate'].dt.strftime('%Y-%m')
                df['DistKm'] = pd.to_numeric(df[dist_col], errors='coerce').fillna(0)
                
                grouped = df.groupby('Month')['DistKm'].sum().to_dict()
                
                for month, km in grouped.items():
                    if pd.notna(month):
                        driving_summary[month] = {"distance_km": round(float(km), 1)}
                print(f"Läste in körstatistik för {len(driving_summary)} månader från Excel.")
            else:
                print("Kunde inte matcha kolumner för datum/sträcka i Excel-filen.")
        except Exception as e:
            print(f"Fel vid inläsning av audi_trips.xlsx: {e}")
            
    return driving_summary

def fetch_all_charge_history(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/api/chargehistory"
    sessions_map = {}
    page_index = 0
    car_mapping = load_car_mapping()

    while True:
        params = {"PageSize": 100, "PageIndex": page_index}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("Data", [])
        
        if not items:
            break

        for s in items:
            session_id = s.get("Id")
            start_time = s.get("StartDateTime", "")
            energy = float(s.get("Energy", 0.0))
            
            raw_user = s.get("UserFullName") or s.get("UserEmail") or s.get("ExternallyEndedBy") or "Okänd"
            user = " ".join(raw_user.split())
            
            # Matcha användare mot bilmappning
            car_info = car_mapping.get(user, {"car": "Övriga bilar", "logo": ""})
            car_name = car_info.get("car", "Övriga bilar")
            car_logo = car_info.get("logo", "")

            cost = calculate_session_cost(start_time, energy)

            sessions_map[session_id] = {
                "id": session_id,
                "date": start_time[:19].replace("T", " "),
                "user": user,
                "car": car_name,
                "car_logo": car_logo,
                "energy": energy,
                "cost": round(cost, 2)
            }

        if len(items) < 100:
            break
        page_index += 1

    return sorted(sessions_map.values(), key=lambda x: x["date"], reverse=True)

def main():
    token = get_access_token()
    sessions = fetch_all_charge_history(token)
    driving_data = process_driving_data()
    
    output_data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions,
        "driving": driving_data
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"Hämtade {len(sessions)} sessioner och sparade kördata till docs/data.json.")

if __name__ == "__main__":
    main()
