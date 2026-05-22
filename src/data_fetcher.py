"""jquants V2 からデータを取得して Parquet に保存。

最適化として、銘柄ごとにループするのではなく **日付指定で一気に全銘柄を取得** する方式を使う。
Premium は500 req/分なので、3年分なら ~750営業日 = 750リクエストで完結する。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd
from tqdm import tqdm

import config
from .jquants_client import JQuantsClient

logger = logging.getLogger(__name__)

MASTER_PATH = config.RAW_DIR / "listed_master.parquet"
DAILY_PATH = config.RAW_DIR / "daily_quotes.parquet"
FINANCIAL_PATH = config.RAW_DIR / "financials.parquet"
ANNOUNCEMENT_PATH = config.RAW_DIR / "announcements.parquet"
TOPIX_PATH = config.RAW_DIR / "topix.parquet"


def _today_business_date() -> date:
    """今日。15時前なら前営業日として扱う簡易処理。"""
    now = datetime.now()
    if now.hour < 15:
        return (now - timedelta(days=1)).date()
    return now.date()


def fetch_master(client: JQuantsClient) -> pd.DataFrame:
    """銘柄マスタを取得（最新時点の全銘柄）"""
    logger.info("銘柄マスタを取得中...")
    df = client.listed_master()
    if df.empty:
        logger.warning("銘柄マスタが空でした")
        return df
    df.to_parquet(MASTER_PATH, index=False)
    logger.info("銘柄マスタ: %d 件保存", len(df))
    return df


def _select_universe(master: pd.DataFrame) -> pd.DataFrame:
    """日経225/JPX400相当の銘柄に絞る。ScaleCat ベース。"""
    if "ScaleCat" not in master.columns:
        logger.warning("ScaleCat カラムが見つからない、フィルタなし")
        return master
    target = {"TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"}
    filtered = master[master["ScaleCat"].isin(target)].copy()
    logger.info("ユニバース絞り込み: %d → %d 件", len(master), len(filtered))
    return filtered


def _trading_dates(client: JQuantsClient, from_date: date, to_date: date) -> List[date]:
    """指定期間内の取引営業日（東証）を返す。"""
    cal = client.trading_calendar(from_date=from_date, to_date=to_date)
    if cal.empty:
        return []
    # HolidayDivision: 1 = 営業日（半休等も含む場合がある）
    if "HolidayDivision" in cal.columns:
        # "1" = 営業日, "0" = 休日 と仮定
        biz = cal[cal["HolidayDivision"].astype(str) == "1"]
    else:
        biz = cal
    dates_col = "Date" if "Date" in biz.columns else biz.columns[0]
    return [pd.to_datetime(d).date() for d in biz[dates_col]]


def fetch_daily_quotes(
    client: JQuantsClient,
    target_codes: Optional[set] = None,
    years: int = config.DAILY_LOOKBACK_YEARS,
    incremental: bool = True,
) -> pd.DataFrame:
    """全銘柄の日足を取得（日付ループ方式）。

    Premium プランの「date 指定で全銘柄一括」エンドポイントを使うことで、
    銘柄ごとループの数百倍速く取得できる。
    """
    end_date = _today_business_date()
    start_date = end_date - timedelta(days=int(years * 365.25))

    existing: Optional[pd.DataFrame] = None
    if incremental and DAILY_PATH.exists():
        logger.info("既存日足データを読み込み中...")
        existing = pd.read_parquet(DAILY_PATH)
        existing["Date"] = pd.to_datetime(existing["Date"])
        last_date = existing["Date"].max()
        if pd.notna(last_date):
            start_date = max(start_date, (last_date - pd.Timedelta(days=7)).date())
            logger.info("差分取得: %s から", start_date)

    # 営業日リストを取得
    logger.info("取引カレンダー取得中...")
    dates = _trading_dates(client, from_date=start_date, to_date=end_date)
    logger.info("対象営業日: %d 日", len(dates))

    frames: List[pd.DataFrame] = []
    for d in tqdm(dates, desc="日足取得（日付別）"):
        try:
            df = client.daily_bars(target_date=d)
            if df.empty:
                continue
            if target_codes is not None and "Code" in df.columns:
                df = df[df["Code"].astype(str).isin(target_codes)]
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            logger.warning("%s: 取得失敗 %s", d, exc)

    new_data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if existing is not None and not existing.empty:
        combined = pd.concat([existing, new_data], ignore_index=True)
    else:
        combined = new_data

    if combined.empty:
        logger.warning("日足データが空です")
        return combined

    combined["Date"] = pd.to_datetime(combined["Date"])
    combined = combined.sort_values(["Code", "Date"]).drop_duplicates(
        subset=["Code", "Date"], keep="last"
    )
    combined.to_parquet(DAILY_PATH, index=False)
    logger.info("日足保存: 累計 %d 件、最新 %s", len(combined), combined["Date"].max())
    return combined


def fetch_financials(client: JQuantsClient, codes: Iterable[str]) -> pd.DataFrame:
    """各銘柄の財務情報を取得。"""
    frames: List[pd.DataFrame] = []
    for code in tqdm(list(codes), desc="財務取得"):
        try:
            df = client.fins_summary(code=code)
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            logger.warning("%s: 財務取得失敗 %s", code, exc)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined.to_parquet(FINANCIAL_PATH, index=False)
        logger.info("財務保存: %d 件", len(combined))
        return combined
    return pd.DataFrame()


def fetch_announcements(client: JQuantsClient) -> pd.DataFrame:
    """決算発表予定。"""
    end_date = _today_business_date() + timedelta(days=120)  # 直近4か月
    df = client.earnings_calendar(from_date=date.today(), to_date=end_date)
    df.to_parquet(ANNOUNCEMENT_PATH, index=False)
    logger.info("決算予定: %d 件", len(df))
    return df


def fetch_topix(client: JQuantsClient, years: int = config.DAILY_LOOKBACK_YEARS) -> pd.DataFrame:
    """TOPIX を取得。"""
    end_date = _today_business_date()
    start_date = end_date - timedelta(days=int(years * 365.25))
    df = client.topix_daily(from_date=start_date, to_date=end_date)
    df.to_parquet(TOPIX_PATH, index=False)
    logger.info("TOPIX保存: %d 件", len(df))
    return df


def fetch_all(incremental: bool = True) -> None:
    """全データを一括取得。"""
    client = JQuantsClient()

    master = fetch_master(client)
    if master.empty:
        logger.error("マスタが空のため中断します")
        return

    universe = _select_universe(master)
    codes = set(universe["Code"].astype(str).tolist())

    fetch_daily_quotes(client, target_codes=codes, incremental=incremental)
    fetch_financials(client, codes=codes)
    try:
        fetch_announcements(client)
    except Exception as exc:
        logger.warning("決算カレンダー取得失敗: %s", exc)
    try:
        fetch_topix(client)
    except Exception as exc:
        logger.warning("TOPIX取得失敗: %s", exc)

    logger.info("全データ取得完了")


# ---------- 読み込みヘルパー ----------
def load_master() -> pd.DataFrame:
    if not MASTER_PATH.exists():
        raise FileNotFoundError("銘柄マスタが未取得です。main.py fetch を先に実行してください。")
    return pd.read_parquet(MASTER_PATH)


def load_daily() -> pd.DataFrame:
    if not DAILY_PATH.exists():
        raise FileNotFoundError("日足データが未取得です。main.py fetch を先に実行してください。")
    df = pd.read_parquet(DAILY_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def load_financials() -> pd.DataFrame:
    if not FINANCIAL_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(FINANCIAL_PATH)


def load_announcements() -> pd.DataFrame:
    if not ANNOUNCEMENT_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(ANNOUNCEMENT_PATH)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
    return df


def load_topix() -> pd.DataFrame:
    if not TOPIX_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(TOPIX_PATH)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
    return df
