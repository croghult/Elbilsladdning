import os
import json
from datetime import datetime, timezone
import requests

ZAPTEC_USERNAME = os.environ["ZAPTEC_USERNAME"]
ZAPTEC_PASSWORD = os.environ["ZAPTEC_PASSWORD"]
ELAREA = "SE3"
BASE_URL = "https://api.zaptec.com"

def get_access_token() -> str:
    url = f"{BASE_URL}/oauth/token"
    payload = {"grant_type": "password", "username": ZAPTEC_USERNAME, "password": ZAPTEC_PASSWORD}
    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]

def fetch_spot_prices(date_str: str) -> dict:
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{date_str.replace('-', '/')}_{ELAREA}.json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return {item["time_start"]: item["SEK_per_kWh"] for item in resp.json()}
    except Exception:
        pass
    return {}

def calculate_session_cost(start_str: str, energy_kwh: float) -> float:
    try:
        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d")
        prices = fetch_spot_prices(date_str)
        hour_key = dt.strftime("%Y-%m-%dT%H:00:00")
        price_per_kwh = prices.get(hour_key, 1.50)
        total_price = price_per_kwh + 0.50 # Påslag för elöverföring/skatt
        return energy_kwh * total_price
    except Exception:
        return energy_kwh * 1.50

def load_car_mapping() -> dict:
    if os.path.exists("car_mapping.json"):
        try:
            with open("car_mapping.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

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
            # Städa bort dubbla mellanslag och specialblanksteg
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
    
    output_data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"Hämtade {len(sessions)} sessioner med uppdaterad bilmappning.")

if __name__ == "__main__":
    main()
