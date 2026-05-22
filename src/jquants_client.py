"""jquants Premium V2 API クライアント。

V2 API は x-api-key ヘッダー方式。
公式ライブラリは V1 専用なので、ここでは requests で直接叩く実装にする。

API仕様: https://jpx-jquants.com/ja/spec/migration-v1-v2
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)


class JQuantsClient:
    """jquants V2 API クライアント。"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or config.JQUANTS_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "jquants V2 の API キーが設定されていません。"
                ".env の JQUANTS_API_KEY に jquants ダッシュボードで発行したキーを記入してください。"
            )
        self.base = config.JQUANTS_API_BASE
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": self.api_key})
        # レート制限緩和のため、リクエスト間に短い待機を入れる（Premium: 500/min = 約8.3/sec）
        self._sleep_sec = 0.15

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """指定エンドポイントを叩いて pagination_key を全部追って ``data`` を結合する。"""
        url = f"{self.base}{path}"
        all_data: List[Dict[str, Any]] = []
        params = dict(params or {})
        retries = 0
        while True:
            try:
                resp = self.session.get(url, params=params, timeout=60)
            except requests.RequestException as exc:
                if retries >= 3:
                    raise
                logger.warning("通信失敗、リトライ %s: %s", retries + 1, exc)
                retries += 1
                time.sleep(2 ** retries)
                continue
            # レート制限なら待つ
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5"))
                logger.info("レート制限。%s秒待機します", wait)
                time.sleep(wait)
                continue
            if not resp.ok:
                # 認証エラーや bad request は即エラー
                raise RuntimeError(
                    f"jquants API エラー status={resp.status_code} url={resp.url} body={resp.text[:300]}"
                )
            payload = resp.json()
            all_data.extend(payload.get("data", []))
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                break
            params["pagination_key"] = pagination_key
            time.sleep(self._sleep_sec)
        time.sleep(self._sleep_sec)
        return all_data

    def _df(self, path: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        data = self._request(path, params)
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)

    @staticmethod
    def _fmt_date(d: Optional[date]) -> Optional[str]:
        if d is None:
            return None
        return d.strftime("%Y-%m-%d")

    # ---------- 銘柄マスタ ----------
    def listed_master(
        self,
        code: Optional[str] = None,
        target_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """上場銘柄一覧 /v2/equities/master"""
        params: Dict[str, Any] = {}
        if code:
            params["code"] = code
        if target_date:
            params["date"] = self._fmt_date(target_date)
        return self._df("/equities/master", params)

    # ---------- 株価日足 ----------
    def daily_bars(
        self,
        code: Optional[str] = None,
        target_date: Optional[date] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """株価四本値（日足） /v2/equities/bars/daily

        code または date のどちらかの指定が必須。
        - code 単独 → 全期間
        - code + from/to → 指定期間
        - date 単独 → その日の全銘柄
        """
        params: Dict[str, Any] = {}
        if code:
            params["code"] = code
        if target_date:
            params["date"] = self._fmt_date(target_date)
        if from_date:
            params["from"] = self._fmt_date(from_date)
        if to_date:
            params["to"] = self._fmt_date(to_date)
        return self._df("/equities/bars/daily", params)

    # ---------- 財務 ----------
    def fins_summary(self, code: Optional[str] = None, target_date: Optional[date] = None) -> pd.DataFrame:
        """財務情報 /v2/fins/summary"""
        params: Dict[str, Any] = {}
        if code:
            params["code"] = code
        if target_date:
            params["date"] = self._fmt_date(target_date)
        return self._df("/fins/summary", params)

    def fins_details(self, code: Optional[str] = None) -> pd.DataFrame:
        """財務諸表(BS/PL/CF) /v2/fins/details"""
        params: Dict[str, Any] = {}
        if code:
            params["code"] = code
        return self._df("/fins/details", params)

    # ---------- 決算カレンダー ----------
    def earnings_calendar(
        self,
        target_date: Optional[date] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """決算発表予定日 /v2/equities/earnings-calendar"""
        params: Dict[str, Any] = {}
        if target_date:
            params["date"] = self._fmt_date(target_date)
        if from_date:
            params["from"] = self._fmt_date(from_date)
        if to_date:
            params["to"] = self._fmt_date(to_date)
        return self._df("/equities/earnings-calendar", params)

    # ---------- 取引カレンダー ----------
    def trading_calendar(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> pd.DataFrame:
        params: Dict[str, Any] = {}
        if from_date:
            params["from"] = self._fmt_date(from_date)
        if to_date:
            params["to"] = self._fmt_date(to_date)
        return self._df("/markets/calendar", params)

    # ---------- TOPIX ----------
    def topix_daily(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """TOPIX指数四本値 /v2/indices/bars/daily/topix"""
        params: Dict[str, Any] = {}
        if from_date:
            params["from"] = self._fmt_date(from_date)
        if to_date:
            params["to"] = self._fmt_date(to_date)
        return self._df("/indices/bars/daily/topix", params)

    # ---------- 指数四本値 ----------
    def indices_daily(
        self,
        code: Optional[str] = None,
        target_date: Optional[date] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> pd.DataFrame:
        params: Dict[str, Any] = {}
        if code:
            params["code"] = code
        if target_date:
            params["date"] = self._fmt_date(target_date)
        if from_date:
            params["from"] = self._fmt_date(from_date)
        if to_date:
            params["to"] = self._fmt_date(to_date)
        return self._df("/indices/bars/daily", params)
