from datetime import date

signals_today = {}

def can_send(symbol):
    today = date.today().isoformat()
    key = f"{symbol}_{today}"

    if key not in signals_today:
        signals_today[key] = 0

    if signals_today[key] >= 3:
        return False

    signals_today[key] += 1
    return True