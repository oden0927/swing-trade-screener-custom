"""エントリポイント。

使い方:
    python main.py fetch                                # jquantsから全データを取得
    python main.py screen                               # スクリーニング → HTML レポート
    python main.py screen --with-charts                 # チャート画像つきレポート
    python main.py screen --date 2026-04-01             # 過去日付でスクリーニング
    python main.py screen --date 2026-04-01 --with-charts  # 過去シグナル+その後の動き
    python main.py all                                  # fetch → screen を一括実行
    python main.py backtest                             # 過去日付の候補の勝率を集計
    python main.py chart 7203                           # 指定銘柄のチャートを生成
    python main.py config-dump                          # 設定を config_summary.txt に書き出す
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def cmd_fetch(args: argparse.Namespace) -> None:
    from src import data_fetcher
    data_fetcher.fetch_all(incremental=not args.full)


def cmd_screen(args: argparse.Namespace) -> None:
    from datetime import date as date_cls
    from src import reporter
    from src.screener import screen_at
    limit = args.limit if args.limit and args.limit > 0 else None
    target_date = None
    if args.date:
        try:
            target_date = date_cls.fromisoformat(args.date)
        except ValueError:
            print(f"日付の形式が不正です: {args.date}（YYYY-MM-DD 形式で指定してください）")
            return
    candidates = screen_at(cutoff_date=target_date, max_candidates=limit)
    out = reporter.render(candidates, with_charts=args.with_charts)
    print(f"\n=== レポート生成完了 ===")
    print(f"候補数: {len(candidates)}")
    if target_date:
        print(f"スクリーニング基準日: {target_date}（過去日付モード）")
    if limit is None:
        print("（上限なしで全候補を出力）")
    else:
        print(f"（上位 {limit} 件に絞り込み）")
    if args.with_charts:
        if target_date:
            print("（チャートに「その後の動き」も表示）")
        else:
            print("（チャート画像を埋め込み済み）")
    print(f"HTML : {out}")
    print(f"open '{out}'  でブラウザに表示できます")


def cmd_chart(args: argparse.Namespace) -> None:
    from src import chart_renderer
    out = chart_renderer.render_code(args.code, lookback=args.lookback)
    if out:
        print(f"=== チャート生成完了 ===")
        print(f"PNG : {out}")
        print(f"open '{out}'  で表示できます")
    else:
        print(f"銘柄 {args.code} のチャート生成に失敗しました")


def cmd_all(args: argparse.Namespace) -> None:
    cmd_fetch(args)
    cmd_screen(args)


def cmd_backtest(args: argparse.Namespace) -> None:
    from src import backtest
    holding = [int(x) for x in args.holding.split(",")] if args.holding else [5, 10, 20]
    df = backtest.run_backtest(
        months_back=args.months,
        sample_interval_days=args.interval,
        holding_days_list=holding,
    )
    summary = backtest.summarize(df, holding)
    print("\n" + summary)
    csv_path, txt_path = backtest.save_results(df, summary)
    print(f"\n=== バックテスト完了 ===")
    print(f"検証件数: {len(df)} 件")
    print(f"CSV     : {csv_path}")
    print(f"集計txt : {txt_path}")


def cmd_config_dump(args: argparse.Namespace) -> None:
    from src import config_dump
    out = config_dump.save_to_file()
    print(f"=== 設定ダンプ完了 ===")
    print(f"ファイル: {out}")
    print(f"open '{out}'  で確認できます")


def main() -> None:
    parser = argparse.ArgumentParser(description="スイングトレード スクリーナー")
    sub = parser.add_subparsers(dest="cmd")

    pf = sub.add_parser("fetch", help="jquants から全データを取得")
    pf.add_argument("--full", action="store_true", help="増分更新ではなく全期間を再取得")
    pf.set_defaults(func=cmd_fetch)

    ps = sub.add_parser("screen", help="スクリーニング実行")
    ps.add_argument("--limit", type=int, default=0,
                    help="上位N件に絞る（0または未指定=上限なし）")
    ps.add_argument("--with-charts", action="store_true",
                    help="ローソク足チャート画像をレポートに埋め込む")
    ps.add_argument("--date", type=str, default=None,
                    help="過去日付でスクリーニング（YYYY-MM-DD）")
    ps.set_defaults(func=cmd_screen)

    pa = sub.add_parser("all", help="fetch → screen を一括実行")
    pa.add_argument("--full", action="store_true")
    pa.add_argument("--limit", type=int, default=0)
    pa.add_argument("--with-charts", action="store_true")
    pa.set_defaults(func=cmd_all)

    pchart = sub.add_parser("chart", help="指定銘柄のチャートPNGを生成")
    pchart.add_argument("code", help="銘柄コード（4桁または5桁、例: 7203）")
    pchart.add_argument("--lookback", type=int, default=180,
                        help="何営業日分のローソク足を表示するか（デフォルト180）")
    pchart.set_defaults(func=cmd_chart)

    pb = sub.add_parser("backtest", help="過去日付で候補の実勝率を集計")
    pb.add_argument("--months", type=int, default=6, help="過去何か月分を検証（デフォルト6）")
    pb.add_argument("--interval", type=int, default=10, help="何営業日おきにサンプリング（デフォルト10）")
    pb.add_argument("--holding", type=str, default="5,10,20",
                    help="保有日数の評価ポイント、カンマ区切り（デフォルト 5,10,20）")
    pb.set_defaults(func=cmd_backtest)

    pc = sub.add_parser("config-dump", help="設定を config_summary.txt に書き出す")
    pc.set_defaults(func=cmd_config_dump)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
