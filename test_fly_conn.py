import psycopg2

fly_regions = ['fra', 'ams', 'cdg', 'lhr', 'iad', 'syd', 'sin']

with open("fly_results.log", "w", encoding="utf-8") as f:
    for r in fly_regions:
        host = f"fly-0-{r}.pooler.supabase.com"
        try:
            conn = psycopg2.connect(
                user="postgres.bjacmfvsojtbdldqthcl",
                password="fFRzP3fEker1C4Hn",
                host=host,
                port=6543,
                database="postgres",
                sslmode="require",
                connect_timeout=5
            )
            f.write(f"SUCCESS: {r}\n")
            conn.close()
            print(f"SUCCESS: {r}")
        except Exception as e:
            f.write(f"FAILED {r}: {str(e).strip()}\n")
            print(f"Failed {r}: {str(e).strip()[:60]}")
