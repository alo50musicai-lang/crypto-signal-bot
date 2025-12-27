def detect_structure(candles):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "BULLISH"
    elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "BEARISH"
    else:
        return "RANGE"