"""
Append scraped rows to a Google Sheet.

config:
    spreadsheet_id:   target spreadsheet id (required)
    worksheet:        worksheet/tab name (default "Sheet1")
    credentials:      service-account credentials as a dict, OR
    credentials_json: the same as a JSON string

The service account must have edit access to the spreadsheet. Writes a header row
when the worksheet is empty, then appends the data rows.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .base import BaseDestination, DeliveryResult

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]


class GoogleSheetsDestination(BaseDestination):
    def validate(self) -> None:
        if not self.config.get('spreadsheet_id'):
            raise ValueError("google_sheets destination requires 'spreadsheet_id'")
        if not (self.config.get('credentials') or self.config.get('credentials_json')):
            raise ValueError("google_sheets destination requires service-account credentials")

    def _credentials_dict(self) -> Dict[str, Any]:
        creds = self.config.get('credentials')
        if creds:
            return creds
        return json.loads(self.config['credentials_json'])

    def deliver(self, columns: List[str], rows: List[Dict[str, Any]]) -> DeliveryResult:
        self.validate()
        if not rows:
            return DeliveryResult(success=True, rows_delivered=0)

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            creds = Credentials.from_service_account_info(self._credentials_dict(), scopes=SCOPES)
            client = gspread.authorize(creds)
            sh = client.open_by_key(self.config['spreadsheet_id'])
            ws_name = self.config.get('worksheet', 'Sheet1')
            try:
                ws = sh.worksheet(ws_name)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title=ws_name, rows=100, cols=max(len(columns), 1))

            values = []
            if not ws.get_all_values():
                values.append(columns)
            for row in rows:
                values.append(['' if row.get(c) is None else str(row.get(c)) for c in columns])

            ws.append_rows(values, value_input_option='RAW')
            return DeliveryResult(success=True, rows_delivered=len(rows),
                                  detail={'worksheet': ws_name})
        except Exception as e:  # noqa: BLE001
            return DeliveryResult(success=False, error=str(e))
