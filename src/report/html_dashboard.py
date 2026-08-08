"""
HTML交互式仪表盘生成器

为A股黄金坑股票数据库生成交互式HTML仪表盘，
包含概览指标、核心池表格、评分分布、赔率散点和行业分布等图表。
"""

import logging
from pathlib import Path
from datetime import date
from typing import Optional, Dict, List

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

logger = logging.getLogger(__name__)


class HTMLDashboard:
    """HTML交互式仪表盘生成器

    生成包含以下图表的交互式HTML仪表盘：
    - 概览指标卡片（各层级数量、平均赔率等）
    - Tier3核心池表格
    - 评分分布直方图
    - 赔率vs评分散点图
    - 行业分布条形图
    """

    def __init__(self, db=None, output_dir: Optional[Path] = None):
        """初始化HTML仪表盘生成器

        Args:
            db: 数据库连接实例（可选）
            output_dir: 仪表盘输出目录，默认为 /workspace/output/dashboards
        """
        self.db = db
        self.output_dir = output_dir or Path('/workspace/output/dashboards')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_dashboard(self, scan_date: Optional[date] = None,
                           tier1: Optional[pd.DataFrame] = None,
                           tier2: Optional[pd.DataFrame] = None,
                           tier3: Optional[pd.DataFrame] = None) -> Path:
        """生成交互式仪表盘HTML

        Args:
            scan_date: 扫描日期，默认为当天
            tier1: 雷达扫描池数据
            tier2: 深度观察池数据
            tier3: 核心黄金坑数据

        Returns:
            生成的HTML文件路径
        """
        scan_date = scan_date or date.today()
        filename = f"黄金坑仪表盘_{scan_date.strftime('%Y%m%d')}.html"
        filepath = self.output_dir / filename

        figures = []

        # 1. 概览指标卡片
        overview = self._create_overview_section(tier1, tier2, tier3)

        # 2. Tier3核心池表格
        if tier3 is not None and not tier3.empty:
            fig_table = self._create_tier3_table(tier3)
            figures.append(fig_table)

        # 3. 评分分布图
        if tier2 is not None and not tier2.empty:
            fig_scores = self._create_score_distribution(tier2)
            figures.append(fig_scores)

        # 4. 赔率vs评分散点图
        if tier3 is not None and not tier3.empty:
            fig_odds = self._create_odds_scatter(tier3)
            figures.append(fig_odds)

        # 5. 行业分布
        if tier1 is not None and not tier1.empty:
            fig_industry = self._create_industry_chart(tier1)
            figures.append(fig_industry)

        # 组装HTML
        html = self._build_html(scan_date, overview, figures)

        filepath.write_text(html, encoding='utf-8')
        logger.info(f"HTML仪表盘已生成: {filepath}")
        return filepath

    def _create_overview_section(self, tier1: Optional[pd.DataFrame],
                                 tier2: Optional[pd.DataFrame],
                                 tier3: Optional[pd.DataFrame]) -> dict:
        """创建概览指标

        Args:
            tier1: 雷达扫描池数据
            tier2: 深度观察池数据
            tier3: 核心黄金坑数据

        Returns:
            概览指标字典
        """
        return {
            'tier1_count': len(tier1) if tier1 is not None else 0,
            'tier2_count': len(tier2) if tier2 is not None else 0,
            'tier3_count': len(tier3) if tier3 is not None else 0,
            'avg_pe_tier3': round(
                tier3['pe_dynamic'].astype(float).mean(), 1
            ) if tier3 is not None and not tier3.empty and 'pe_dynamic' in tier3.columns else 0,
            'avg_odds_tier3': round(
                tier3['odds_ratio'].astype(float).mean(), 2
            ) if tier3 is not None and not tier3.empty and 'odds_ratio' in tier3.columns else 0,
        }

    def _create_tier3_table(self, df: pd.DataFrame) -> go.Figure:
        """创建Tier3核心池表格图

        Args:
            df: Tier3核心黄金坑数据

        Returns:
            Plotly表格Figure
        """
        display_cols = []
        headers = []
        if 'symbol' in df.columns:
            display_cols.append('symbol')
            headers.append('代码')
        if 'name' in df.columns:
            display_cols.append('name')
            headers.append('名称')
        if 'price' in df.columns:
            display_cols.append('price')
            headers.append('价格')
        if 'pe_dynamic' in df.columns:
            display_cols.append('pe_dynamic')
            headers.append('PE')
        if 'total_score' in df.columns:
            display_cols.append('total_score')
            headers.append('评分')
        if 'odds_ratio' in df.columns:
            display_cols.append('odds_ratio')
            headers.append('赔率')
        if 'rating' in df.columns:
            display_cols.append('rating')
            headers.append('评级')
        if 'position_type' in df.columns:
            display_cols.append('position_type')
            headers.append('仓位')

        cells = []
        for col in display_cols:
            vals = df[col].tolist()
            cells.append([round(v, 2) if isinstance(v, float) else str(v) for v in vals])

        fig = go.Figure(data=[go.Table(
            header=dict(
                values=headers,
                fill_color='#1F4E79',
                font=dict(color='white', size=12),
                align='center'
            ),
            cells=dict(
                values=cells,
                fill_color='#F5F5F5',
                font=dict(size=11),
                align='center',
                height=30
            )
        )])
        fig.update_layout(title='核心黄金坑 (Tier 3)', height=100 + 35 * len(df))
        return fig

    def _create_score_distribution(self, df: pd.DataFrame) -> go.Figure:
        """创建评分分布图

        Args:
            df: 深度观察池数据

        Returns:
            Plotly直方图Figure
        """
        if 'total_score' in df.columns:
            fig = px.histogram(
                df, x='total_score', nbins=10,
                title='综合评分分布 (Tier 2)',
                labels={'total_score': '综合评分', 'count': '数量'},
                color_discrete_sequence=['#1F4E79']
            )
        elif 'quality_score' in df.columns:
            fig = px.histogram(
                df, x='quality_score', nbins=10,
                title='质量评分分布 (Tier 2)',
                labels={'quality_score': '质量评分', 'count': '数量'},
                color_discrete_sequence=['#1F4E79']
            )
        else:
            fig = go.Figure()
            fig.update_layout(title='评分数据不足')
        return fig

    def _create_odds_scatter(self, df: pd.DataFrame) -> go.Figure:
        """创建赔率vs评分散点图

        Args:
            df: Tier3核心黄金坑数据

        Returns:
            Plotly散点图Figure
        """
        x_col = 'total_score' if 'total_score' in df.columns else 'quality_score'
        y_col = 'odds_ratio'

        if x_col not in df.columns or y_col not in df.columns:
            fig = go.Figure()
            fig.update_layout(title='赔率-评分数据不足')
            return fig

        hover_data = []
        if 'symbol' in df.columns:
            hover_data.append('symbol')
        if 'name' in df.columns:
            hover_data.append('name')

        fig = px.scatter(
            df, x=x_col, y=y_col,
            hover_data=hover_data if hover_data else None,
            title='赔率 vs 评分 (Tier 3)',
            labels={x_col: '综合评分', y_col: '赔率'},
            color='rating' if 'rating' in df.columns else None,
            size='position_pct' if 'position_pct' in df.columns else None,
        )
        fig.add_hline(y=2.0, line_dash="dash", line_color="green",
                       annotation_text="赔率=2.0")
        fig.add_vline(x=7.0, line_dash="dash", line_color="blue",
                       annotation_text="评分=7.0")
        return fig

    def _create_industry_chart(self, df: pd.DataFrame) -> go.Figure:
        """创建行业分布图

        Args:
            df: 雷达扫描池数据

        Returns:
            Plotly条形图Figure
        """
        if 'industry' not in df.columns:
            fig = go.Figure()
            fig.update_layout(title='行业分布数据不足')
            return fig

        industry_counts = df['industry'].value_counts().head(15)
        fig = px.bar(
            x=industry_counts.values, y=industry_counts.index,
            orientation='h', title='Tier 1 行业分布 (Top 15)',
            labels={'x': '数量', 'y': '行业'},
            color_discrete_sequence=['#1F4E79']
        )
        fig.update_layout(yaxis={'categoryorder': 'total ascending'})
        return fig

    def _build_html(self, scan_date: date, overview: dict,
                    figures: List[go.Figure]) -> str:
        """组装完整HTML

        Args:
            scan_date: 扫描日期
            overview: 概览指标字典
            figures: Plotly图表列表

        Returns:
            完整HTML字符串
        """
        # 转换figures为HTML div
        plot_divs = []
        for i, fig in enumerate(figures):
            div = fig.to_html(full_html=False,
                              include_plotlyjs='cdn' if i == 0 else False)
            plot_divs.append(f'<div class="chart-container">{div}</div>')

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股黄金坑数据库 - {scan_date.strftime('%Y-%m-%d')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #f0f2f5; color: #333; }}
        .header {{ background: linear-gradient(135deg, #1F4E79, #2B6BA8); color: white; padding: 30px; text-align: center; }}
        .header h1 {{ font-size: 28px; margin-bottom: 5px; }}
        .header p {{ font-size: 14px; opacity: 0.85; }}
        .overview {{ display: flex; justify-content: center; gap: 20px; padding: 20px; flex-wrap: wrap; }}
        .card {{ background: white; border-radius: 10px; padding: 20px 30px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.1); min-width: 120px; }}
        .card .number {{ font-size: 32px; font-weight: bold; color: #1F4E79; }}
        .card .label {{ font-size: 12px; color: #666; margin-top: 5px; }}
        .card.highlight {{ border: 2px solid #C00000; }}
        .card.highlight .number {{ color: #C00000; }}
        .content {{ max-width: 1200px; margin: 0 auto; padding: 0 20px 40px; }}
        .chart-container {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .footer {{ text-align: center; padding: 20px; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>A股黄金坑股票数据库</h1>
        <p>扫描日期: {scan_date.strftime('%Y年%m月%d日')} | 三层递进筛选体系</p>
    </div>

    <div class="overview">
        <div class="card">
            <div class="number">{overview.get('tier1_count', 0)}</div>
            <div class="label">雷达池 (Tier 1)</div>
        </div>
        <div class="card">
            <div class="number">{overview.get('tier2_count', 0)}</div>
            <div class="label">观察池 (Tier 2)</div>
        </div>
        <div class="card highlight">
            <div class="number">{overview.get('tier3_count', 0)}</div>
            <div class="label">核心黄金坑 (Tier 3)</div>
        </div>
        <div class="card">
            <div class="number">{overview.get('avg_odds_tier3', 0):.1f}x</div>
            <div class="label">平均赔率</div>
        </div>
    </div>

    <div class="content">
        {"".join(plot_divs)}
    </div>

    <div class="footer">
        <p>A股黄金坑股票数据库 &copy; 2026 | 基于SOR3.0投资框架 | 数据仅供参考，不构成投资建议</p>
    </div>
</body>
</html>'''
        return html
