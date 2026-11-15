import os
import json
from datetime import datetime, timezone
import requests
import pandas as pd

# --- Funktion för att läsa in kördata från Audi Excel-filen ---
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

# --- Resten av dina Zaptec-funktioner här ---
def get_access_token():
    # ... din kod för att hämta Zaptec-token ...
    pass

def fetch_all_charge_history(token):
    # ... din kod för att hämta laddsessioner ...
    return []

def main():
    # token = get_access_token()
    # sessions = fetch_all_charge_history(token)
    sessions = [] # Om du testar utan Zaptec-inloggning just nu
    
    # Hämta kördata från Excel-filen
    driving_data = process_driving_data()
    
    output_data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions,
        "driving": driving_data
    }

    # Se till att mappen 'docs' finns
    os.makedirs("docs", exist_ok=True)

    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print("data.json har sparats med kördata!")

if __name__ == "__main__":
    main()
