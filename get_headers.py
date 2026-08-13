import urllib.request
import urllib.error

with open("headers.log", "w", encoding="utf-8") as f:
    try:
        urllib.request.urlopen('https://bjacmfvsojtbdldqthcl.supabase.co')
    except urllib.error.HTTPError as e:
        for k, v in e.headers.items():
            f.write(f"{k}: {v}\n")
    except Exception as e:
        f.write(f"Other issue: {e}\n")
