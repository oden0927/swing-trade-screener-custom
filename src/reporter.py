"""HTMLレポート生成。Jinja2 テンプレートに候補を流し込む。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from tqdm import tqdm

import config
from .environment import judge_market_regime
from .screener import Candidate
from . import data_fetcher

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render(candidates: List[Candidate], with_charts: bool = False) -> Path:
    """候補リストから HTMLレポート を生成し、保存先パスを返す。"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(config.REPORT_TEMPLATE_NAME)

    # 全体地合いをレポートに含めるため再判定
    topix = data_fetcher.load_topix()
    market = judge_market_regime(topix)

    # チャート画像（base64）の準備
    chart_map = {}
    if with_charts and candidates:
        from . import chart_renderer
        daily = data_fetcher.load_daily()
        logger.info("チャート画像を生成中（%d件）...", len(candidates))
        for c in tqdm(candidates, desc="チャート生成"):
            b64 = chart_renderer.render_as_base64(c, daily, lookback=120)
            if b64:
                chart_map[c.code] = b64

    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    premium_count = sum(1 for c in candidates if c.score >= config.PREMIUM_SCORE_THRESHOLD)
    out_html = template.render(
        report_date=report_date,
        candidates=candidates,
        chart_map=chart_map,
        max_size=len(candidates),  # 上限なし運用に変更、実際の候補数を表示
        market_regime=market.label,
        market_regime_label={
            "UPTREND": "上昇相場",
            "BOX": "ボックス相場",
            "DOWNTREND": "下落相場",
            "UNCLEAR": "判定保留",
        }.get(market.label, "判定保留"),
        market_confidence=market.confidence,
        market_regime_note=market.notes,
        premium_threshold=config.PREMIUM_SCORE_THRESHOLD,
        premium_count=premium_count,
    )

    out_path = config.REPORT_DIR / f"screen_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    out_path.write_text(out_html, encoding="utf-8")

    # 最新版へのシンボリックリンク的な役割で latest.html を別途作る
    latest = config.REPORT_DIR / "latest.html"
    latest.write_text(out_html, encoding="utf-8")

    logger.info("レポート生成: %s", out_path)
    return out_path
