import logging
import time
import urllib3
from optionchainfetcher import detect_gamma_burst, get_pcr_and_option_data

# Suppress SSL warnings from third-party NorenRestApiPy library
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def fetch_option_chain_data():
    """
    Periodically fetch option chain snapshot using the handler.
    Returns only the DataFrame part of the result.
    """
    try:
        # get_pcr_and_option_data returns (merged_df, pcr, prediction)
        merged_df, pcr, prediction = get_pcr_and_option_data(force_refresh=True)
        gamma_burst = detect_gamma_burst(merged_df)

        if gamma_burst and gamma_burst["signal"] == "GAMMA BURST":
            print("⚠️ High Gamma activity detected! Possible breakout zone.")
        if merged_df is None:
            logging.warning("OptionChainRunner: No option chain data fetched.")
            return None
        return merged_df
    except Exception as e:
        logging.exception("OptionChainRunner error: %s", e)
        return None


def main_():
    """Standalone entry point for OptionChainRunner."""
    logging.basicConfig(level=logging.INFO)
    print("Running OptionChainRunner main_...")
    df = fetch_option_chain_data()
    if df is not None:
        print(df.head())
    else:
        print("No option chain data fetched.")


if __name__ == "__main__":
    main_()
