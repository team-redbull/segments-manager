import logging
import io
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import pandas as pd
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..utils.database_utils import DatabaseUtils
from ..utils.error_handlers import handle_db_errors, retry_on_network_error
from ..utils.logging_decorators import log_operation_timing

logger = logging.getLogger(__name__)

class ExportService:
    """Service class for data export operations"""

    @staticmethod
    def _prepare_export_data(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Prepare segments data for export (shared by CSV and Excel exports)

        Args:
            segments: List of segment dictionaries from database

        Returns:
            List of dictionaries formatted for export with readable column names
        """
        export_data = []
        for segment in segments:
            export_data.append({
                'Type': segment.get('type', ''),
                'Site': segment.get('site', ''),
                'VLAN ID': segment.get('vlan_id', ''),
                'EPG Name': segment.get('epg_name', ''),
                'Segment': segment.get('segment', ''),
                'DHCP': 'Yes' if segment.get('dhcp', False) else 'No',
                'Cluster Name': segment.get('cluster_name', '') if segment.get('cluster_name') else 'Available',
                'Allocated At': segment.get('allocated_at', ''),
                'Released': 'Yes' if segment.get('released', False) else 'No',
                'Released At': segment.get('released_at', ''),
                'Status': segment.get('status', '')
            })
        return export_data

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("export_segments_csv", threshold_ms=3000)
    async def export_segments_csv(site: Optional[str] = None, status: Optional[str] = None) -> StreamingResponse:
        """Export segments data as CSV"""
        segments = await DatabaseUtils.get_segments_with_filters(site=site, status=status)

        # Prepare data for export using shared helper method
        export_data = ExportService._prepare_export_data(segments)

        # Create DataFrame
        df = pd.DataFrame(export_data)

        # Convert to CSV
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()
        csv_buffer.close()

        # Generate filename with timezone-aware timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        site_suffix = f"_{site}" if site else ""
        status_suffix = f"_{status.lower()}" if status else ""
        filename = f"segments{site_suffix}{status_suffix}_{timestamp}.csv"

        # Return streaming response
        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("export_segments_excel", threshold_ms=3000)
    async def export_segments_excel(site: Optional[str] = None, status: Optional[str] = None) -> StreamingResponse:
        """Export segments data as Excel"""
        segments = await DatabaseUtils.get_segments_with_filters(site=site, status=status)

        # Prepare data for export using shared helper method
        export_data = ExportService._prepare_export_data(segments)

        # Create DataFrame
        df = pd.DataFrame(export_data)

        # Convert to Excel
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Segments', index=False)

            # Auto-adjust column widths
            worksheet = writer.sheets['Segments']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if cell.value is not None and len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except (AttributeError, TypeError, ValueError):
                        # Skip cells with non-string values or errors
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        excel_buffer.seek(0)

        # Generate filename with timezone-aware timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        site_suffix = f"_{site}" if site else ""
        status_suffix = f"_{status.lower()}" if status else ""
        filename = f"segments{site_suffix}{status_suffix}_{timestamp}.xlsx"

        # Return streaming response
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    
    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("export_stats_csv", threshold_ms=2000)
    async def export_stats_csv() -> StreamingResponse:
        """Export site statistics as CSV"""
        from ..config.settings import SITES

        # Get stats for all sites
        stats_data = []
        for site in SITES:
            stats = await DatabaseUtils.get_site_statistics(site)
            stats_data.append(stats)

        # Create DataFrame
        df = pd.DataFrame(stats_data)

        # Convert to CSV
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()
        csv_buffer.close()

        # Generate filename with timezone-aware timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"site_statistics_{timestamp}.csv"

        # Return streaming response
        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )