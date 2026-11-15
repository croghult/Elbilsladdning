import os
import json
from datetime import datetime, timezone
import requests

ZAPTEC_USERNAME = os.environ["ZAPTEC_USERNAME"]
ZAPTEC_PASSWORD = os.environ["ZAPTEC_PASSWORD"]
BASE_URL = "https://api.zaptec.com"

def get_access_token() -> str:
    url = f"{BASE_URL}/oauth/token"
    payload = {"grant_type": "password", "username": ZAPTEC_USERNAME, "password": ZAPTEC_PASSWORD}
    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]

def fetch_all_charge_history(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/api/chargehistory"
    sessions_map = {}
    page_index = 0

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
            sessions_map[session_id] = {
                "id": session_id,
                "date": s.get("StartDateTime", "")[:19].replace("T", " "),
                "user": s.get("UserFullName") or s.get("UserEmail") or s.get("ExternallyEndedBy") or "Okänd",
                "energy": float(s.get("Energy", 0.0))
            }

        if len(items) < 100:
            break
        page_index += 1

    sorted_sessions = sorted(sessions_map.values(), key=lambda x: x["date"], reverse=True)
    return sorted_sessions

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
    
    print(f"Hämtade totalt {len(sessions)} unika laddsessioner och sparade till docs/data.json")

if __name__ == "__main__":
    main()
