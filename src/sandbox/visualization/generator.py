"""
Visualization Generator

Generates Plotly visualizations from data with:
- Auto chart type detection
- Data aggregation for large datasets
- Insight extraction
- Safe code execution for custom visualizations
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from sandbox.core.config import get_config, DataSharingConfig
from sandbox.core.exceptions import ExecutionError, OutputSizeLimitError
from sandbox.core.logging import get_logger
from sandbox.execution.base import ExecutionContext, ExecutionMetrics, ExecutionStatus

logger = get_logger(__name__)


class ChartType(str, Enum):
    """Supported chart types."""
    AUTO = "auto"
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    TABLE = "table"
    AREA = "area"
    HISTOGRAM = "histogram"


@dataclass
class VisualizationResult:
    """Result of visualization generation."""
    request_id: str
    status: ExecutionStatus
    plotly_spec: dict[str, Any] | None = None
    insight: str | None = None
    explanation: str | None = None
    chart_type: ChartType = ChartType.AUTO
    data_points: int = 0
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "request_id": self.request_id,
            "status": self.status.value,
            "chart_type": self.chart_type.value,
            "data_points": self.data_points,
            "metrics": self.metrics.to_dict(),
        }
        if self.plotly_spec:
            result["plotly_spec"] = self.plotly_spec
        if self.insight:
            result["insight"] = self.insight
        if self.explanation:
            result["explanation"] = self.explanation
        if self.error_message:
            result["error"] = self.error_message
        return result


class VisualizationGenerator:
    """
    Generates Plotly visualizations from data.

    Features:
    - Auto chart type detection based on data characteristics
    - Data aggregation for large datasets
    - Customizable chart generation
    - Insight extraction
    """

    def __init__(self, data_sharing_config: DataSharingConfig | None = None) -> None:
        config = get_config()
        self.data_sharing = data_sharing_config or config.data_sharing
        self.max_data_points = self.data_sharing.max_visualization_data_points
        self._logger = get_logger("visualization")

    async def generate(
        self,
        context: ExecutionContext,
        *,
        data: list[dict[str, Any]] | pd.DataFrame,
        instruction: str | None = None,
        chart_type: ChartType = ChartType.AUTO,
        title: str | None = None,
    ) -> VisualizationResult:
        """
        Generate a visualization from data.

        Args:
            context: Execution context
            data: Data to visualize (list of dicts or DataFrame)
            instruction: Natural language instruction for visualization
            chart_type: Desired chart type (AUTO for automatic detection)
            title: Chart title

        Returns:
            VisualizationResult with Plotly spec
        """
        metrics = ExecutionMetrics()
        self._logger.info(
            "visualization_started",
            request_id=context.request_id,
            chart_type=chart_type.value,
            instruction_preview=instruction[:50] if instruction else None,
        )

        try:
            # Convert to DataFrame if needed
            if isinstance(data, list):
                df = pd.DataFrame(data)
            else:
                df = data

            if df.empty:
                return VisualizationResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.ERROR,
                    error_message="No data to visualize",
                    metrics=metrics,
                )

            # Aggregate if too many data points
            original_rows = len(df)
            if len(df) > self.max_data_points:
                df = self._aggregate_data(df)
                self._logger.info(
                    "data_aggregated",
                    request_id=context.request_id,
                    original_rows=original_rows,
                    aggregated_rows=len(df),
                )

            # Detect chart type if auto
            if chart_type == ChartType.AUTO:
                chart_type = self._detect_chart_type(df, instruction)

            # Generate Plotly spec
            plotly_spec = self._generate_plotly_spec(df, chart_type, title, instruction)

            # Validate output size
            spec_size = len(json.dumps(plotly_spec).encode("utf-8"))
            max_size_bytes = (context.max_output_size_kb or 1024) * 1024

            if spec_size > max_size_bytes:
                raise OutputSizeLimitError(
                    limit_kb=max_size_bytes // 1024,
                    actual_kb=spec_size // 1024,
                )

            # Generate insight
            insight = self._generate_insight(df, chart_type)

            metrics.complete()
            metrics.rows_processed = original_rows
            metrics.rows_returned = len(df)

            result = VisualizationResult(
                request_id=context.request_id,
                status=ExecutionStatus.SUCCESS,
                plotly_spec=plotly_spec,
                insight=insight,
                chart_type=chart_type,
                data_points=len(df),
                metrics=metrics,
            )

            self._logger.info(
                "visualization_completed",
                request_id=context.request_id,
                chart_type=chart_type.value,
                data_points=len(df),
                spec_size_kb=spec_size // 1024,
            )

            return result

        except OutputSizeLimitError:
            raise
        except Exception as e:
            metrics.complete()
            self._logger.error(
                "visualization_failed",
                request_id=context.request_id,
                error=str(e),
            )
            return VisualizationResult(
                request_id=context.request_id,
                status=ExecutionStatus.ERROR,
                error_message=str(e),
                metrics=metrics,
            )

    def _detect_chart_type(
        self, df: pd.DataFrame, instruction: str | None = None
    ) -> ChartType:
        """Detect the best chart type based on data characteristics."""
        # Check instruction for hints
        if instruction:
            instruction_lower = instruction.lower()
            if any(w in instruction_lower for w in ["line", "trend", "time", "over time"]):
                return ChartType.LINE
            if any(w in instruction_lower for w in ["bar", "compare", "comparison"]):
                return ChartType.BAR
            if any(w in instruction_lower for w in ["pie", "proportion", "percentage", "share"]):
                return ChartType.PIE
            if any(w in instruction_lower for w in ["scatter", "correlation", "relationship"]):
                return ChartType.SCATTER
            if any(w in instruction_lower for w in ["heat", "matrix"]):
                return ChartType.HEATMAP
            if any(w in instruction_lower for w in ["table", "list"]):
                return ChartType.TABLE

        # Analyze data characteristics
        num_cols = df.select_dtypes(include=["number"]).columns.tolist()
        cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
        date_cols = df.select_dtypes(include=["datetime64"]).columns.tolist()

        # Time series: has date column + numeric column
        if date_cols and num_cols:
            return ChartType.LINE

        # Few categories with values: bar chart
        if len(cat_cols) == 1 and len(num_cols) >= 1:
            unique_cats = df[cat_cols[0]].nunique()
            if unique_cats <= 10:
                return ChartType.BAR
            elif unique_cats <= 5:
                return ChartType.PIE

        # Two numeric columns: scatter
        if len(num_cols) >= 2 and len(cat_cols) == 0:
            return ChartType.SCATTER

        # Multiple numeric columns: heatmap or bar
        if len(num_cols) > 2:
            if len(df) <= 20:
                return ChartType.HEATMAP
            return ChartType.BAR

        # Default to bar chart
        return ChartType.BAR

    def _generate_plotly_spec(
        self,
        df: pd.DataFrame,
        chart_type: ChartType,
        title: str | None,
        instruction: str | None,
    ) -> dict[str, Any]:
        """Generate Plotly specification for the chart."""
        import plotly.express as px
        import plotly.graph_objects as go

        # Identify columns
        num_cols = df.select_dtypes(include=["number"]).columns.tolist()
        cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
        date_cols = df.select_dtypes(include=["datetime64"]).columns.tolist()

        # Use first appropriate columns
        x_col = date_cols[0] if date_cols else (cat_cols[0] if cat_cols else df.columns[0])
        y_col = num_cols[0] if num_cols else df.columns[1] if len(df.columns) > 1 else df.columns[0]

        # Generate chart based on type
        if chart_type == ChartType.LINE:
            fig = px.line(df, x=x_col, y=y_col, title=title)

        elif chart_type == ChartType.BAR:
            fig = px.bar(df, x=x_col, y=y_col, title=title)

        elif chart_type == ChartType.PIE:
            fig = px.pie(df, names=x_col, values=y_col, title=title)

        elif chart_type == ChartType.SCATTER:
            y2_col = num_cols[1] if len(num_cols) > 1 else y_col
            fig = px.scatter(df, x=y_col, y=y2_col, title=title)

        elif chart_type == ChartType.AREA:
            fig = px.area(df, x=x_col, y=y_col, title=title)

        elif chart_type == ChartType.HISTOGRAM:
            fig = px.histogram(df, x=y_col, title=title)

        elif chart_type == ChartType.HEATMAP:
            # For heatmap, need numeric matrix
            numeric_df = df.select_dtypes(include=["number"])
            fig = px.imshow(numeric_df.corr(), title=title or "Correlation Heatmap")

        elif chart_type == ChartType.TABLE:
            fig = go.Figure(data=[go.Table(
                header=dict(values=list(df.columns)),
                cells=dict(values=[df[col].tolist() for col in df.columns])
            )])
            if title:
                fig.update_layout(title=title)

        else:
            # Default to bar
            fig = px.bar(df, x=x_col, y=y_col, title=title)

        # Apply common styling
        fig.update_layout(
            template="plotly_white",
            font=dict(family="Inter, sans-serif"),
            margin=dict(l=40, r=40, t=60, b=40),
        )

        # Convert to dict spec
        return fig.to_dict()

    def _aggregate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate data to reduce data points."""
        # Identify columns
        date_cols = df.select_dtypes(include=["datetime64"]).columns.tolist()
        num_cols = df.select_dtypes(include=["number"]).columns.tolist()
        cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

        # If time series, resample
        if date_cols and num_cols:
            date_col = date_cols[0]
            df = df.set_index(date_col)

            # Determine resample frequency based on data range
            date_range = (df.index.max() - df.index.min()).days
            if date_range > 365 * 2:
                freq = "M"  # Monthly
            elif date_range > 90:
                freq = "W"  # Weekly
            else:
                freq = "D"  # Daily

            agg_dict = {col: "sum" for col in num_cols}
            df = df.resample(freq).agg(agg_dict).reset_index()

        # If categorical, limit to top N
        elif cat_cols:
            cat_col = cat_cols[0]
            if num_cols:
                num_col = num_cols[0]
                # Keep top categories by sum of numeric column
                top_cats = df.groupby(cat_col)[num_col].sum().nlargest(50).index
                df = df[df[cat_col].isin(top_cats)]

        # If still too large, sample
        if len(df) > self.max_data_points:
            df = df.sample(n=self.max_data_points, random_state=42)

        return df

    def _generate_insight(self, df: pd.DataFrame, chart_type: ChartType) -> str:
        """Generate a simple insight about the data."""
        insights = []

        num_cols = df.select_dtypes(include=["number"]).columns.tolist()

        if num_cols:
            for col in num_cols[:2]:  # Limit to first 2 numeric columns
                total = df[col].sum()
                avg = df[col].mean()
                max_val = df[col].max()
                min_val = df[col].min()

                insights.append(
                    f"{col}: Total={total:,.2f}, Avg={avg:,.2f}, "
                    f"Range=[{min_val:,.2f} - {max_val:,.2f}]"
                )

        if not insights:
            insights.append(f"Data contains {len(df)} records across {len(df.columns)} columns")

        return " | ".join(insights)

    async def generate_from_code(
        self,
        context: ExecutionContext,
        *,
        code: str,
        data: list[dict[str, Any]],
    ) -> VisualizationResult:
        """
        Generate visualization by executing custom Python code.

        The code should set `plotly_figure`, `insight`, and `explanation` variables.

        Args:
            context: Execution context
            code: Python code to execute
            data: Data available to the code

        Returns:
            VisualizationResult
        """
        from sandbox.execution.python_executor import PythonExecutor

        executor = PythonExecutor()
        metrics = ExecutionMetrics()

        try:
            # Execute the code
            result = await executor.execute(
                context,
                code=code,
                input_data={"data": data},
            )

            if not result.is_success():
                return VisualizationResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.ERROR,
                    error_message=result.error_message,
                    metrics=result.metrics,
                )

            # Extract visualization from variables
            variables = result.variables
            plotly_spec = variables.get("plotly_figure")
            insight = variables.get("insight")
            explanation = variables.get("explanation")

            if not plotly_spec:
                return VisualizationResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.ERROR,
                    error_message="Code did not produce a plotly_figure variable",
                    metrics=result.metrics,
                )

            # Validate spec structure
            if not isinstance(plotly_spec, dict):
                return VisualizationResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.ERROR,
                    error_message="plotly_figure must be a dictionary",
                    metrics=result.metrics,
                )

            if "data" not in plotly_spec or not isinstance(plotly_spec.get("data"), list):
                return VisualizationResult(
                    request_id=context.request_id,
                    status=ExecutionStatus.ERROR,
                    error_message="plotly_figure must have a 'data' array",
                    metrics=result.metrics,
                )

            metrics.complete()

            return VisualizationResult(
                request_id=context.request_id,
                status=ExecutionStatus.SUCCESS,
                plotly_spec=plotly_spec,
                insight=insight if isinstance(insight, str) else None,
                explanation=explanation if isinstance(explanation, str) else None,
                data_points=len(data),
                metrics=metrics,
            )

        except Exception as e:
            metrics.complete()
            return VisualizationResult(
                request_id=context.request_id,
                status=ExecutionStatus.ERROR,
                error_message=str(e),
                metrics=metrics,
            )
