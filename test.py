"""
China A-share stock dashboard powered by AKShare.

Run:
    streamlit run test.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stock_data import (
    format_large_number,
    get_a_share_spot,
    get_stock_history,
    search_stocks,
    to_plain_code,
)

st.set_page_config(
    page_title="A股行情 | AKShare",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .metric-up { color: #ef5350; }
    .metric-down { color: #26a69a; }
    div[data-testid="stMetricValue"] { font-size: 1.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner=False)
def load_spot_data() -> tuple[pd.DataFrame, str]:
    return get_a_share_spot()


@st.cache_data(ttl=300, show_spinner=False)
def load_history(code: str, days: int, adjust: str) -> tuple[pd.DataFrame, str]:
    return get_stock_history(code, days=days, adjust=adjust)


def pct_color(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "inherit"
    return "#ef5350" if value >= 0 else "#26a69a"


def render_candlestick(df: pd.DataFrame, title: str) -> None:
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df["date"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing_line_color="#ef5350",
                decreasing_line_color="#26a69a",
                name="K线",
            )
        ]
    )
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        height=480,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_white",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_volume_chart(df: pd.DataFrame) -> None:
    colors = ["#ef5350" if c >= o else "#26a69a" for c, o in zip(df["close"], df["open"])]
    fig = go.Figure(
        data=[
            go.Bar(
                x=df["date"],
                y=df["volume"],
                marker_color=colors,
                name="成交量",
            )
        ]
    )
    fig.update_layout(
        title="成交量",
        height=220,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_white",
    )
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.title("📈 A股行情看板")
    st.caption("数据来源：AKShare（东方财富 / 新浪 / 腾讯，自动切换）")

    with st.sidebar:
        st.header("查询设置")
        search_query = st.text_input("股票代码或名称", placeholder="例如 600519 或 贵州茅台")
        days = st.selectbox("历史区间", [60, 120, 180, 365], index=2)
        adjust = st.selectbox("复权方式", ["qfq", "hfq", ""], format_func=lambda x: {"qfq": "前复权", "hfq": "后复权", "": "不复权"}[x])
        refresh = st.button("刷新数据", type="primary", use_container_width=True)
        if refresh:
            st.cache_data.clear()

    try:
        with st.spinner("正在加载全市场行情..."):
            spot_df, spot_source = load_spot_data()
    except Exception as exc:  # noqa: BLE001
        st.error(f"行情加载失败：{exc}")
        st.info(
            "若频繁失败，可能是数据源限流。请稍后再试，或在浏览器打开 "
            "[东方财富行情页](https://quote.eastmoney.com/) 完成验证后重试。"
        )
        return

    st.success(f"已加载 {len(spot_df):,} 只股票行情（来源：{spot_source}）")

    up = int((spot_df["pct_change"] > 0).sum())
    down = int((spot_df["pct_change"] < 0).sum())
    flat = int((spot_df["pct_change"] == 0).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("上涨", f"{up:,}")
    c2.metric("下跌", f"{down:,}")
    c3.metric("平盘", f"{flat:,}")
    avg_pct = spot_df["pct_change"].mean()
    c4.metric("平均涨跌幅", f"{avg_pct:.2f}%" if pd.notna(avg_pct) else "-")

    tab_market, tab_search, tab_detail = st.tabs(["市场概览", "股票搜索", "个股详情"])

    with tab_market:
        left, right = st.columns(2)
        gainers = spot_df.dropna(subset=["pct_change"]).nlargest(15, "pct_change")
        losers = spot_df.dropna(subset=["pct_change"]).nsmallest(15, "pct_change")

        display_cols = [c for c in ["code", "name", "price", "pct_change", "volume", "amount"] if c in spot_df.columns]
        with left:
            st.subheader("涨幅榜 Top 15")
            st.dataframe(
                gainers[display_cols].rename(
                    columns={
                        "code": "代码",
                        "name": "名称",
                        "price": "最新价",
                        "pct_change": "涨跌幅(%)",
                        "volume": "成交量",
                        "amount": "成交额",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        with right:
            st.subheader("跌幅榜 Top 15")
            st.dataframe(
                losers[display_cols].rename(
                    columns={
                        "code": "代码",
                        "name": "名称",
                        "price": "最新价",
                        "pct_change": "涨跌幅(%)",
                        "volume": "成交量",
                        "amount": "成交额",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("成交额 Top 20")
        if "amount" in spot_df.columns:
            top_amount = spot_df.dropna(subset=["amount"]).nlargest(20, "amount")
            st.dataframe(
                top_amount[display_cols].rename(
                    columns={
                        "code": "代码",
                        "name": "名称",
                        "price": "最新价",
                        "pct_change": "涨跌幅(%)",
                        "volume": "成交量",
                        "amount": "成交额",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with tab_search:
        results = search_stocks(search_query, spot_df)
        st.write(f"匹配到 **{len(results)}** 只股票")
        st.dataframe(
            results[display_cols].rename(
                columns={
                    "code": "代码",
                    "name": "名称",
                    "price": "最新价",
                    "pct_change": "涨跌幅(%)",
                    "volume": "成交量",
                    "amount": "成交额",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    with tab_detail:
        default_code = search_query or "600519"
        detail_code = st.text_input("查看个股", value=default_code, key="detail_code")
        plain_code = to_plain_code(detail_code)

        row_mask = spot_df["code"].str.endswith(plain_code, na=False)
        matches = spot_df[row_mask]
        if matches.empty:
            st.warning("未找到该股票，请检查代码或名称。")
            return

        stock = matches.iloc[0]
        stock_name = stock.get("name", plain_code)
        stock_label = f"{stock.get('code', plain_code)} {stock_name}"

        m1, m2, m3, m4 = st.columns(4)
        price = stock.get("price")
        pct = stock.get("pct_change")
        m1.metric("最新价", f"{price:.2f}" if pd.notna(price) else "-")
        m2.metric("涨跌幅", f"{pct:.2f}%" if pd.notna(pct) else "-", delta=f"{pct:.2f}%" if pd.notna(pct) else None)
        m3.metric("成交量", format_large_number(stock.get("volume")))
        m4.metric("成交额", format_large_number(stock.get("amount")))

        try:
            with st.spinner(f"正在加载 {stock_label} 历史数据..."):
                hist_df, hist_source = load_history(stock.get("code", plain_code), days=days, adjust=adjust)
        except Exception as exc:  # noqa: BLE001
            st.error(f"历史行情加载失败：{exc}")
            return

        st.caption(f"历史数据来源：{hist_source} | 共 {len(hist_df)} 个交易日")
        render_candlestick(hist_df, f"{stock_label} 日K线")
        if "volume" in hist_df.columns:
            render_volume_chart(hist_df)

        with st.expander("历史数据表"):
            show_hist = hist_df.copy()
            show_hist["date"] = show_hist["date"].dt.strftime("%Y-%m-%d")
            st.dataframe(show_hist, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
