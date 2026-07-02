"""Reads and writes for ``locations`` reference data."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class LocationsRepository:
    TABLE_NAME = "locations"

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def find_id_by_city_state_country_tx(
        self,
        *,
        city: str,
        state_code: str,
        country: str,
    ) -> str | None:
        city_s = self._clean(city)
        state_s = self._clean(state_code)
        country_s = self._clean(country)
        if not city_s or not state_s or not country_s:
            return None

        row = self._session.execute(
            text(
                f"""
                SELECT id::text
                FROM {self.TABLE_NAME}
                WHERE country = :country
                  AND state_code = :state_code
                  AND lower(city) = lower(:city)
                LIMIT 1
                """
            ),
            {"country": country_s, "state_code": state_s, "city": city_s},
        ).first()
        return str(row[0]) if row and row[0] else None

    def insert_location_tx(
        self,
        *,
        city: str,
        state: str | None,
        state_code: str,
        postal_code: str | None,
        country: str,
    ) -> str | None:
        """Insert one location row; return id, or ``None`` on unique-key conflict."""
        city_s = self._clean(city)
        state_s = self._clean(state)
        state_code_s = self._clean(state_code)
        postal_s = self._clean(postal_code)
        country_s = self._clean(country)
        if not city_s or not state_code_s or not country_s:
            return None

        params = {
            "city": city_s,
            "state": state_s,
            "state_code": state_code_s,
            "postal_code": postal_s,
            "country": country_s,
        }
        try:
            row = self._session.execute(
                text(
                    f"""
                    INSERT INTO {self.TABLE_NAME}
                        (city, state, state_code, postal_code, country)
                    VALUES
                        (:city, :state, :state_code, :postal_code, :country)
                    RETURNING id::text
                    """
                ),
                params,
            ).first()
        except IntegrityError:
            return None
        return str(row[0]) if row and row[0] else None

    def get_postal_code_by_id(self, location_id: str) -> str | None:
        lid = self._clean(location_id)
        if not lid:
            return None
        row = self._session.execute(
            text(
                f"""
                SELECT postal_code
                FROM {self.TABLE_NAME}
                WHERE id = CAST(:location_id AS uuid)
                """
            ),
            {"location_id": lid},
        ).first()
        if not row or row[0] is None:
            return None
        postal = str(row[0]).strip()
        return postal if postal else None
